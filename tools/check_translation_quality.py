"""翻譯品質檢查工具：掃描 translated.json，偵測殘留英文、亂碼、簡體中文，輸出分類報告。

用法：
    python tools/check_translation_quality.py --input .tmp/<slug>/translated.json --output output/<slug>_quality_report.txt --slug <slug>
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# High-frequency simplified Chinese characters that differ from traditional
SIMPLIFIED_CHARS = {
    "这": "這", "个": "個", "来": "來", "说": "說", "认": "認",
    "数": "數", "关": "關", "对": "對", "为": "為", "从": "從",
    "进": "進", "们": "們", "与": "與", "还": "還", "过": "過",
    "发": "發", "现": "現", "开": "開", "问": "問", "实": "實",
    "样": "樣", "学": "學", "时": "時", "没": "沒", "会": "會",
    "动": "動", "机": "機", "长": "長", "点": "點", "东": "東",
    "书": "書", "见": "見", "电": "電", "车": "車", "让": "讓",
}

# Japanese kana ranges (Katakana + Hiragana)
_KANA_RE = re.compile(r"[\u30A0-\u30FF\u3040-\u309F]")

# Korean Hangul (Syllables + Jamo)
_HANGUL_RE = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")

# Markdown artifacts from LLM hallucination
_MARKDOWN_RE = re.compile(r"(```|^\*\*.*\*\*$|^\d+\.\s)", re.MULTILINE)


def detect_residual_english(translation: str, original: str) -> tuple[bool, str]:
    """Detect untranslated or residual English in translation."""
    if not translation or not translation.strip():
        return True, "完全未翻譯（空白）"

    if translation.strip() == original.strip():
        return True, "完全未翻譯（與原文相同）"

    long_english_words = re.findall(r'\b[A-Za-z]{5,}\b', translation)
    if not long_english_words:
        return False, ""

    english_chars = sum(1 for c in translation if c.isascii() and c.isalpha())
    total_chars = len(translation.replace(" ", "").replace("\n", ""))
    if total_chars == 0:
        return False, ""

    ratio = english_chars / total_chars
    if ratio > 0.20:
        sample = "、".join(long_english_words[:5])
        return True, f"疑似殘留英文（{sample}）"

    return False, ""


def detect_garbled(translation: str) -> tuple[bool, str]:
    """Detect garbled text: Japanese kana, Korean hangul, markdown artifacts from LLM."""
    if not translation or not translation.strip():
        return False, ""

    # Japanese kana in Chinese translation
    kana_matches = _KANA_RE.findall(translation)
    if kana_matches:
        sample = "".join(kana_matches[:5])
        return True, f"亂碼（含日文假名：{sample}）"

    # Korean hangul in Chinese translation
    hangul_matches = _HANGUL_RE.findall(translation)
    if hangul_matches:
        sample = "".join(hangul_matches[:5])
        return True, f"亂碼（含韓文：{sample}）"

    # Markdown formatting artifacts
    if _MARKDOWN_RE.search(translation):
        return True, "亂碼（LLM 輸出含 markdown 格式）"

    return False, ""


def detect_simplified_chinese(translation: str) -> tuple[bool, str]:
    """Detect simplified Chinese characters (target is Traditional Chinese)."""
    if not translation or not translation.strip():
        return False, ""

    found = []
    for simp, trad in SIMPLIFIED_CHARS.items():
        if simp in translation:
            found.append(f"{simp}→{trad}")

    if len(found) >= 2:
        sample = "、".join(found[:5])
        return True, f"簡體中文（{sample}）"

    return False, ""


def detect_length_anomaly(translation: str, original: str) -> tuple[bool, str]:
    """Detect translations with abnormal length ratio (likely hallucination or truncation).
    English→Chinese typically yields 40-80% character count."""
    if not translation or not translation.strip() or not original or not original.strip():
        return False, ""

    orig_len = len(original.replace(" ", "").replace("\n", ""))
    trans_len = len(translation.replace(" ", "").replace("\n", ""))

    if orig_len < 10:
        return False, ""  # too short to judge

    ratio = trans_len / orig_len

    if ratio > 2.0:
        return True, f"長度異常（譯文是原文的 {ratio:.1f} 倍，疑似 LLM 幻覺）"
    if ratio < 0.15:
        return True, f"長度異常（譯文僅原文的 {ratio:.0%}，疑似截斷）"

    return False, ""


# All checkers: (category_name, check_function, function_needs_original)
CHECKERS = [
    ("殘留英文", detect_residual_english, True),
    ("亂碼", detect_garbled, False),
    ("簡體中文", detect_simplified_chinese, False),
    ("長度異常", detect_length_anomaly, True),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="翻譯品質報告生成工具")
    parser.add_argument("--input", required=True, help="translated.json 路徑")
    parser.add_argument("--output", required=True, help="報告輸出路徑（.txt）")
    parser.add_argument("--slug", required=True, help="字幕檔 slug（用於報告標題）")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"[錯誤] 找不到輸入檔案：{input_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)

    # Run all checkers, group results by category
    categorized: dict[str, list[dict]] = {name: [] for name, _, _ in CHECKERS}

    for seg in data:
        translation = seg.get("translation", "")
        original = seg.get("text", "")

        for cat_name, checker, needs_original in CHECKERS:
            if needs_original:
                found, reason = checker(translation, original)
            else:
                found, reason = checker(translation)
            if found:
                categorized[cat_name].append({
                    "index": seg["index"],
                    "timestamp": seg["timestamp"],
                    "text": original,
                    "translation": translation,
                    "reason": reason,
                })

    # Build report
    lines = [
        f"翻譯品質報告：{args.slug}",
        f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"總段落數：{total}",
        "",
        "問題摘要：",
    ]

    total_issues = 0
    for cat_name, _, _ in CHECKERS:
        count = len(categorized[cat_name])
        total_issues += count
        lines.append(f"  {cat_name}：{count} 段")

    lines.append("=" * 45)

    if total_issues == 0:
        lines.append("")
        lines.append("（無品質問題）")
    else:
        for cat_name, _, _ in CHECKERS:
            items = categorized[cat_name]
            if not items:
                continue
            lines.append("")
            lines.append(f"【{cat_name}】（{len(items)} 段）")
            lines.append("")
            for seg in items:
                lines.append(f"[段落 {seg['index']}]  {seg['timestamp']}")
                lines.append(f"原文：{seg['text']}")
                lines.append(f"譯文：{seg['translation']}")
                lines.append(f"原因：{seg['reason']}")
                lines.append("")

    report = "\n".join(lines)
    output_path.write_text(report, encoding="utf-8")

    print(f"[完成] 品質報告：{total_issues}/{total} 段有問題，已輸出至 {output_path}")


if __name__ == "__main__":
    main()
