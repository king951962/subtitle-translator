"""Improve subtitle translation quality using LLM-based evaluation and retranslation.

Usage:
    python tools/improve_translations.py --input <json> [--backend gemini|ollama]
        [--model MODEL] [--batch-size 20] [--threshold 3]
        [--dry-run] [--scan-only] [--fix-only] [--max-fixes N]

Phases:
    1. PRE-FILTER  - Skip obviously-fine segments locally (no LLM needed)
    2. SCAN        - Batch-evaluate remaining segments with LLM (score 1-5)
    3. FIX         - Retranslate flagged segments with context
    4. SYNC        - Update translated.json + progress + regenerate VTT
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fix_hallucinations import (
    TECH_WHITELIST,
    _TECH_LOWER,
    _ENGLISH_WORD_RE,
    _CJK_RE,
    detect_hallucinations,
    apply_deterministic_fixes,
)
from translate_segments import _clean

OLLAMA_URL = "http://localhost:11434/api/chat"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Backend defaults
DEFAULT_MODELS = {"gemini": "gemini-2.0-flash", "ollama": "qwen2.5:7b"}

# Global state set in main()
_backend = "gemini"
_gemini_api_key = ""


def _load_env_key(key: str) -> str:
    """Read a key from .env file in project root."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return ""
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return ""


# ---------------------------------------------------------------------------
# Gemini API helper
# ---------------------------------------------------------------------------
def call_gemini(
    model: str,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    max_retries: int = 3,
) -> str:
    """Call Gemini API. Returns content string or empty on failure."""
    url = f"{GEMINI_URL}/{model}:generateContent?key={_gemini_api_key}"
    payload = json.dumps({
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }).encode("utf-8")

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            print(f"  [retry {attempt + 1}] HTTP {e.code}: {body}", file=sys.stderr)
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
            elif attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  [retry {attempt + 1}] {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return ""


# ---------------------------------------------------------------------------
# Ollama API helper
# ---------------------------------------------------------------------------
def call_ollama(
    model: str,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    max_retries: int = 3,
) -> str:
    """Call Ollama chat API. Returns content string or empty on failure."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }).encode("utf-8")

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["message"]["content"].strip()
        except Exception as e:
            if "Connection refused" in str(e):
                print("[錯誤] 無法連線至 Ollama，請先執行：ollama serve", file=sys.stderr)
                sys.exit(1)
            print(f"  [retry {attempt + 1}] {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return ""


# ---------------------------------------------------------------------------
# Backend dispatcher
# ---------------------------------------------------------------------------
def call_llm(
    model: str,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> str:
    """Route to the active backend."""
    if _backend == "gemini":
        return call_gemini(model, system, user, temperature, max_tokens)
    return call_ollama(model, system, user, temperature, max_tokens)


# ---------------------------------------------------------------------------
# Pre-filter: skip segments that are obviously fine
# ---------------------------------------------------------------------------
def pre_filter(seg: dict) -> bool:
    """Return True if segment needs LLM evaluation (suspicious).
    Return False if segment looks fine (skip it).
    """
    trans = seg.get("translation", "")
    orig = seg.get("text", "")

    if not trans or not trans.strip():
        return True  # empty = suspicious

    # Must contain CJK
    if not _CJK_RE.search(trans):
        return True

    # Check for hard hallucinations
    if detect_hallucinations(seg):
        return True

    # Check for non-whitelisted ALL-CAPS English words (almost certainly untranslated)
    allcaps_words = re.findall(r"\b[A-Z]{4,}\b", trans)
    suspicious_caps = [w for w in allcaps_words if w.lower() not in _TECH_LOWER]
    if suspicious_caps:
        return True

    # Check for CJK-dash-English hybrid (e.g., 非常-realistic, 我-added了)
    if re.search(r"[\u4e00-\u9fff]-[a-zA-Z]|[a-zA-Z]-[\u4e00-\u9fff]", trans):
        return True

    # Check for Markdown italic leaking (e.g., _draper_)
    if re.search(r"_[a-zA-Z][a-zA-Z\s]*_", trans):
        return True

    # Check for phrasal verb split (e.g., 檢查 IN, 銷售 ON)
    if re.search(r"[\u4e00-\u9fff]\s+(?:IN|ON|UP|OUT|OFF|BY|TO)\b", trans, re.IGNORECASE):
        return True

    # Check for non-whitelisted English words (4+ chars, 1+ in CJK context)
    words = _ENGLISH_WORD_RE.findall(trans)
    suspicious_words = [w for w in words if w.lower() not in _TECH_LOWER]
    if len(suspicious_words) >= 1:
        return True

    # Length ratio check
    orig_len = len(orig.replace(" ", ""))
    trans_len = len(trans.replace(" ", ""))
    if orig_len > 10:
        ratio = trans_len / orig_len
        if ratio > 1.8 or ratio < 0.15:
            return True

    # Structural damage markers
    if re.search(r"\[(?!BLANK_AUDIO)", trans):
        return True
    if "\n\n" in trans:
        return True

    return False


# ---------------------------------------------------------------------------
# Phase 1: Batch evaluation
# ---------------------------------------------------------------------------
EVAL_SYSTEM_PROMPT = """你是字幕翻譯品質審核員。以下是英文字幕及其繁體中文翻譯。
請評估每段翻譯的品質（1-5 分），並標記具體問題。

評分標準：
5 = 完美：準確、自然、符合台灣用語
4 = 良好：小瑕疵但不影響理解
3 = 尚可：有明顯問題但勉強可讀
2 = 差：嚴重影響理解的錯誤
1 = 不可用：未翻譯、亂碼、完全錯誤

問題類別代碼（可多選）：
- UNTRANSLATED: 英文單字未翻譯（如 POLITELY, MANUAL, Definitely 混在中文裡）
- FRAGMENTED: 斷字損壞（如 "ewith", "gether"）
- MISTRANSLATION: 意思翻錯
- BROKEN_STRUCTURE: 句子結構斷裂不完整
- REDUNDANT: 中英重複表達同一意思（如 "Exact 精確"）
- UNNATURAL: 不自然的直譯，台灣人不會這樣說話

注意：技術術語（如 Claude Code, API, GitHub, webhook, token, MCP, CLI, VSCode, React, Docker 等）保留英文是正確的，不算 UNTRANSLATED。

只輸出 JSON 陣列，不要有任何其他文字。格式：
[{"index": 10, "score": 2, "issues": ["UNTRANSLATED", "BROKEN_STRUCTURE"]}]
若分數為 4 或 5，issues 可為空陣列。"""


def _parse_eval_json(text: str) -> list[dict]:
    """Parse LLM evaluation output, handling common formatting issues."""
    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Extract JSON from markdown code fence
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find array in text
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    return []


def evaluate_batch(model: str, segments: list[dict]) -> list[dict]:
    """Evaluate a batch of segments. Returns [{index, score, issues}]."""
    user_content = json.dumps(
        [{"index": s["index"], "text": s["text"],
          "translation": s.get("translation", "")}
         for s in segments],
        ensure_ascii=False,
        indent=None,
    )

    response = call_llm(
        model, EVAL_SYSTEM_PROMPT, user_content,
        temperature=0.1, max_tokens=2048,
    )

    if not response:
        return []

    results = _parse_eval_json(response)

    # Validate and normalize
    valid = []
    valid_indices = {s["index"] for s in segments}
    for item in results:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        score = item.get("score", 5)
        issues = item.get("issues", [])
        if idx in valid_indices and isinstance(score, (int, float)):
            valid.append({
                "index": idx,
                "score": int(score),
                "issues": issues if isinstance(issues, list) else [],
            })

    return valid


# ---------------------------------------------------------------------------
# Phase 2: Context-aware retranslation
# ---------------------------------------------------------------------------
RETRANSLATE_SYSTEM = """你是台灣專業字幕翻譯員，專精影片字幕翻譯。
請根據上下文重新翻譯標記為 [TARGET] 的段落。

嚴格規則：
- 技術術語（Claude Code, API, GitHub, webhook, token, MCP, CLI 等）保留英文
- 語氣自然，適合字幕閱讀，像台灣人說話的方式
- 注意與前後段落的語意銜接
- [BLANK_AUDIO] 保持原樣不翻譯
- 這可能是一個句子片段（字幕常見），不需要是完整句子

翻譯步驟：
1. [分析] 原文的核心意思是什麼？有哪些關鍵術語？
2. [上下文] 前後段落在講什麼？這段在整體脈絡中的角色？
3. [初譯] 先寫出第一版翻譯
4. [推敲] 檢查初譯：是否自然？是否有殘留英文？是否符合台灣用語？有沒有更好的表達方式？
5. [譯文] 輸出最終的繁體中文譯文

請用以下格式回覆：
[分析] ...
[上下文] ...
[初譯] ...
[推敲] ...
[譯文] ..."""


REVIEW_SYSTEM = """你是翻譯品質審查員。請檢查以下譯文並修正任何問題。

檢查重點：
- 意思是否準確？
- 用語是否自然（像台灣人說話）？
- 是否有多餘的英文或說明文字？
- 技術術語（API, CLI, GitHub 等）保留英文是正確的

只輸出修正後的譯文，不加任何說明。若譯文已完美，原樣輸出即可。"""


def retranslate_with_context(
    model: str,
    target_seg: dict,
    context_before: list[dict],
    context_after: list[dict],
    issues: list[str],
    temperature: float = 0.15,
) -> str:
    """Retranslate a segment with surrounding context."""
    system = RETRANSLATE_SYSTEM

    # Issue-specific guidance
    issue_guidance = {
        "UNTRANSLATED": "所有英文都必須翻譯為中文，只有技術術語（如 API, CLI, GitHub 等）可保留英文",
        "BROKEN_STRUCTURE": "確保句子結構完整通順，即使原文是片段也要讓中文讀起來流暢",
        "UNNATURAL": "用台灣人日常說話的方式表達，避免逐字直譯",
        "REDUNDANT": "不要中英文重複表達同一意思，選擇一種語言即可",
        "MISTRANSLATION": "仔細理解原文意思後再翻譯，確保語意準確",
        "FRAGMENTED": "注意原文可能有斷字問題，先還原完整單字再翻譯",
    }
    if issues:
        guidance = [issue_guidance[i] for i in issues if i in issue_guidance]
        if guidance:
            system += "\n\n修正重點：\n" + "\n".join(f"- {g}" for g in guidance)
        else:
            system += f"\n\n原翻譯的問題：{', '.join(issues)}\n請特別注意修正上述問題。"

    parts = []
    if context_before:
        parts.append("上下文（前）：")
        for seg in context_before:
            parts.append(f"[{seg['index']}] 原文：{seg['text']}")
            parts.append(f"       譯文：{seg.get('translation', '')}")
        parts.append("")

    parts.append("[TARGET] 需重譯：")
    parts.append(f"[{target_seg['index']}] 原文：{target_seg['text']}")
    old_trans = target_seg.get("translation", "")
    if old_trans:
        parts.append(f"       舊譯（有問題）：{old_trans}")
    parts.append("")

    if context_after:
        parts.append("上下文（後）：")
        for seg in context_after:
            parts.append(f"[{seg['index']}] 原文：{seg['text']}")
            parts.append(f"       譯文：{seg.get('translation', '')}")

    user_content = "\n".join(parts)

    # Phase 1: Chain-of-thought translation
    raw = call_llm(model, system, user_content, temperature=temperature, max_tokens=800)
    if not raw:
        return ""

    # Extract [譯文] from chain-of-thought output
    m = re.search(r"\[譯文\]\s*(.+)", raw, re.DOTALL)
    result = m.group(1).strip() if m else raw

    result = _clean(result)
    result = re.sub(r"^\[\d+\]\s*", "", result)
    result = apply_deterministic_fixes(result)

    if not result or not _CJK_RE.search(result):
        return ""

    # Phase 2: Self-review refinement
    review_user = (
        f"原文：{target_seg['text']}\n"
        f"譯文：{result}\n\n"
        "只輸出修正後的譯文。"
    )
    refined = call_llm(model, REVIEW_SYSTEM, review_user, temperature=0.1, max_tokens=200)
    if refined:
        refined = _clean(refined)
        refined = re.sub(r"^\[\d+\]\s*", "", refined)
        refined = apply_deterministic_fixes(refined)
        if refined and _CJK_RE.search(refined):
            result = refined

    return result


# ---------------------------------------------------------------------------
# Progress file management
# ---------------------------------------------------------------------------
def load_progress(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"scan_completed_up_to": 0, "flagged": {}, "fixed": [], "fix_failed": []}


def save_progress(path: Path, progress: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="改善字幕翻譯品質（LLM 評估+重譯）")
    parser.add_argument("--input", "-i", required=True, help="translated.json 路徑")
    parser.add_argument("--backend", choices=["gemini", "ollama"], default="ollama",
                        help="LLM 後端（預設 ollama）")
    parser.add_argument("--model", default=None,
                        help="模型名稱（預設依 backend：gemini-2.0-flash / qwen2.5:7b）")
    parser.add_argument("--batch-size", type=int, default=20, help="每批評估段數")
    parser.add_argument("--threshold", type=int, default=4, help="評分門檻（≤此值需修復）")
    parser.add_argument("--dry-run", action="store_true", help="只掃描評分，不修改")
    parser.add_argument("--scan-only", action="store_true", help="只執行 Phase 1")
    parser.add_argument("--fix-only", action="store_true", help="跳過掃描，用現有 flagged 清單")
    parser.add_argument("--max-fixes", type=int, default=0, help="限制修復數量（0=不限）")
    args = parser.parse_args()

    # Set backend and model
    global _backend, _gemini_api_key
    _backend = args.backend
    if args.model is None:
        args.model = DEFAULT_MODELS[_backend]

    if _backend == "gemini":
        _gemini_api_key = _load_env_key("GEMINI_API_KEY")
        if not _gemini_api_key:
            print("[錯誤] 找不到 GEMINI_API_KEY，請在 .env 中設定", file=sys.stderr)
            sys.exit(1)

    print(f"[設定] backend={_backend}, model={args.model}", file=sys.stderr)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[錯誤] 找不到檔案：{input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)
    seg_map = {seg["index"]: seg for seg in data}
    progress_path = Path(str(input_path) + ".improve_progress.json")
    progress = load_progress(progress_path)

    # -----------------------------------------------------------------------
    # Phase 1: Pre-filter + LLM scan
    # -----------------------------------------------------------------------
    if not args.fix_only:
        print(f"[Phase 1] 預篩 {total} 段翻譯...", file=sys.stderr)

        suspicious = []
        skipped = 0
        already_scanned_up_to = progress.get("scan_completed_up_to", 0)

        for seg in data:
            if seg["index"] < already_scanned_up_to and not args.dry_run:
                continue
            if pre_filter(seg):
                suspicious.append(seg)
            else:
                skipped += 1

        print(
            f"  預篩結果：{len(suspicious)} 段需 LLM 評估，{skipped} 段跳過",
            file=sys.stderr,
        )

        # Batch evaluate
        print(f"\n[Phase 2] LLM 批次評分...", file=sys.stderr)
        batches = [
            suspicious[i:i + args.batch_size]
            for i in range(0, len(suspicious), args.batch_size)
        ]

        for batch_idx, batch in enumerate(batches, 1):
            print(
                f"  批次 {batch_idx}/{len(batches)}（段落 {batch[0]['index']}-{batch[-1]['index']}）...",
                file=sys.stderr,
            )
            results = evaluate_batch(args.model, batch)

            # Map results back
            result_map = {r["index"]: r for r in results}

            for seg in batch:
                idx = str(seg["index"])
                if seg["index"] in result_map:
                    r = result_map[seg["index"]]
                    if r["score"] <= args.threshold:
                        progress["flagged"][idx] = {
                            "score": r["score"],
                            "issues": r["issues"],
                        }
                else:
                    # LLM didn't return result for this segment - flag it
                    if idx not in progress["flagged"]:
                        progress["flagged"][idx] = {
                            "score": 0,
                            "issues": ["EVAL_MISSING"],
                        }

            # Update progress
            progress["scan_completed_up_to"] = batch[-1]["index"] + 1
            if not args.dry_run:
                save_progress(progress_path, progress)

        # Print summary
        flagged = progress["flagged"]
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"掃描完成：{len(flagged)} 段需修復（門檻 ≤{args.threshold}）", file=sys.stderr)

        # Issue distribution
        issue_counts: dict[str, int] = {}
        for info in flagged.values():
            for issue in info.get("issues", []):
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        for issue in sorted(issue_counts, key=issue_counts.get, reverse=True):
            print(f"  {issue}：{issue_counts[issue]} 段", file=sys.stderr)
        print(f"{'='*50}\n", file=sys.stderr)

        if args.dry_run or args.scan_only:
            # Print flagged segments
            for seg in data:
                idx = str(seg["index"])
                if idx in flagged:
                    info = flagged[idx]
                    issues_str = ", ".join(info.get("issues", []))
                    print(
                        f"[{seg['index']}] {seg['timestamp']}  "
                        f"score={info['score']}  {issues_str}",
                        file=sys.stderr,
                    )
                    print(f"  原文：{seg['text'][:90]}", file=sys.stderr)
                    print(
                        f"  譯文：{seg.get('translation', '')[:90]}",
                        file=sys.stderr,
                    )
                    print(file=sys.stderr)

            mode = "dry-run" if args.dry_run else "scan-only"
            print(f"[{mode}] 完成，未修改任何檔案。", file=sys.stderr)
            if not args.dry_run:
                save_progress(progress_path, progress)
            return

    # -----------------------------------------------------------------------
    # Phase 3: Fix flagged segments
    # -----------------------------------------------------------------------
    flagged = progress["flagged"]
    already_fixed = set(progress.get("fixed", []))

    to_fix = [
        (int(idx), info)
        for idx, info in flagged.items()
        if int(idx) not in already_fixed and int(idx) in seg_map
    ]
    to_fix.sort(key=lambda x: x[0])

    if args.max_fixes > 0:
        to_fix = to_fix[:args.max_fixes]

    print(
        f"[Phase 3] 修復 {len(to_fix)} 段（已修復 {len(already_fixed)} 段）...",
        file=sys.stderr,
    )

    # Build ordered index list for context lookup
    ordered_indices = [seg["index"] for seg in data]
    idx_to_pos = {idx: pos for pos, idx in enumerate(ordered_indices)}

    success_count = 0
    fail_count = 0

    for i, (idx, info) in enumerate(to_fix, 1):
        seg = seg_map[idx]
        issues = info.get("issues", [])
        print(
            f"  [{i}/{len(to_fix)}] 段落 {idx} ({seg['timestamp']}) "
            f"score={info.get('score', '?')} {issues}...",
            file=sys.stderr,
        )

        # Get context
        pos = idx_to_pos.get(idx, 0)
        ctx_before = [data[j] for j in range(max(0, pos - 8), pos)]
        ctx_after = [data[j] for j in range(pos + 1, min(len(data), pos + 9))]

        # Try translation with retry at higher temperature on failure
        accepted = False
        for attempt, temp in enumerate([0.15, 0.3]):
            if attempt > 0:
                print(f"    ↻ 重試（temperature={temp}）...", file=sys.stderr)

            new_trans = retranslate_with_context(
                args.model, seg, ctx_before, ctx_after, issues,
                temperature=temp,
            )

            if not new_trans or not _CJK_RE.search(new_trans):
                continue

            # Validate: no hard hallucinations
            fake_seg = {"translation": new_trans, "text": seg["text"]}
            hard_issues = detect_hallucinations(fake_seg)
            hard_cats = {c for c, _ in hard_issues} & {
                "japanese_kana", "korean_hangul", "vietnamese", "cyrillic",
                "code_injection", "random_nonsense",
                "meta_commentary", "mixed_english",
            }

            # Length ratio check
            orig_len = len(seg["text"].replace(" ", ""))
            trans_len = len(new_trans.replace(" ", ""))
            if orig_len > 10:
                ratio = trans_len / orig_len
                if ratio > 2.0 or ratio < 0.15:
                    hard_cats.add("length_anomaly")

            if not hard_cats:
                seg["translation"] = new_trans
                success_count += 1
                progress.setdefault("fixed", []).append(idx)
                print(f"    ✓ 成功", file=sys.stderr)
                accepted = True
                break
            else:
                print(
                    f"    ⚠ 驗證失敗：{hard_cats}",
                    file=sys.stderr,
                )

        if not accepted:
            fail_count += 1
            progress.setdefault("fix_failed", []).append(idx)
            print(f"    ✗ 重譯失敗，保留原譯", file=sys.stderr)

        # Save progress every 10 segments
        if i % 10 == 0:
            save_progress(progress_path, progress)

    save_progress(progress_path, progress)
    print(
        f"\n  修復結果：成功 {success_count}，失敗 {fail_count}",
        file=sys.stderr,
    )

    # -----------------------------------------------------------------------
    # Phase 4: Sync
    # -----------------------------------------------------------------------
    print("\n[Phase 4] 同步檔案...", file=sys.stderr)

    # Apply deterministic fixes on all segments
    for seg in data:
        seg["translation"] = apply_deterministic_fixes(seg.get("translation", ""))

    # Write translated.json
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  translated.json 已更新", file=sys.stderr)

    # Sync translation progress file
    trans_progress_path = Path(str(input_path) + ".progress.json")
    trans_progress = {str(seg["index"]): seg["translation"] for seg in data}
    with open(trans_progress_path, "w", encoding="utf-8") as f:
        json.dump(trans_progress, f, ensure_ascii=False)
    print(f"  progress file 已同步", file=sys.stderr)

    # Regenerate VTT
    slug = input_path.parent.name
    vtt_path = input_path.parent.parent.parent / "output" / f"{slug}_translated.vtt"
    if not vtt_path.parent.exists():
        vtt_path = Path("output") / f"{slug}_translated.vtt"

    subprocess.run(
        [sys.executable, "tools/format_output.py",
         "--input", str(input_path),
         "--output", str(vtt_path)],
        check=True,
    )
    print(f"  VTT 已重新生成：{vtt_path}", file=sys.stderr)

    print(f"\n[完成] 成功修復 {success_count} 段翻譯", file=sys.stderr)


if __name__ == "__main__":
    main()
