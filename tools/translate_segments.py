"""翻譯字幕段落：逐段呼叫 Ollama，純文字輸出，斷點續傳。

用法：
    python tools/translate_segments.py --input <json> --output <json> [--model gemma3:12b]
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from subtitle_utils import load_segments

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = """你是一位擁有十年經驗的台灣在地專業影視字幕翻譯員。
你的唯一任務是將使用者輸入的英文字幕，準確且流暢地翻譯成「台灣繁體中文」。

【嚴格遵守以下規則，否則翻譯將被退回】：

絕對禁止簡體字：輸出的每一個字都必須是標準的繁體中文。

嚴格使用台灣慣用語：絕對禁止出現中國大陸的拼音直譯或網路用語。

(範例：必須用「螢幕」替換「屏幕」，用「影片」替換「視頻」，用「程式」替換「程序」，用「記憶體」替換「內存」，用「伺服器」替換「服務器」，用「解析度」替換「分辨率」)。

語氣自然：請根據上下文進行意譯，避免生硬的逐字機翻，讓台灣觀眾讀起來順暢自然。

純淨輸出：你只需要輸出翻譯後的字幕文字。絕對不要加上任何解釋、問候語、或是類似「好的，這是你的翻譯」等廢話。

絕對不要保留未翻譯的英文大寫單字：遇到英文詞彙時，必須翻譯成對應的中文（技術術語如 API、CLI、GitHub 等除外）。

絕對不要用連字號連接中英文：例如「非常-realistic」或「我-added了」都是錯誤格式。

不要輸出 Markdown 格式：不要使用星號、底線等標記符號。"""

USER_PREFIX = ""


def _clean(text: str) -> str:
    """移除模型回傳的說明文字，只保留譯文。"""
    import re
    # 若含「可以被翻譯為」句型，取最後一個「...」內容
    m = re.search(r"「([^」]+)」\s*$", text)
    if m:
        return m.group(1).strip()
    # 移除以英文引號包住的原文行（如 "..." 可以被翻譯為...）
    lines = [l for l in text.splitlines() if not re.match(r'^["\u201c].*["\u201d].*翻譯', l)]
    result = "\n".join(lines).strip()
    # 去除整段被引號包住的情況（"譯文" 或 「譯文」）
    result = re.sub(r'^[「\u201c"](.*)[」\u201d"]$', r'\1', result, flags=re.DOTALL)
    return result.strip()


def translate_one(model: str, text: str, max_retries: int = 3) -> str:
    """翻譯單一字幕文字，回傳純繁體中文字串。失敗則回傳空字串。"""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PREFIX + text},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 120},
    }).encode("utf-8")

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            result: str = data["message"]["content"].strip()
            return _clean(result)

        except OSError as e:
            if "Connection refused" in str(e) or "refused" in str(e).lower():
                print("[錯誤] 無法連線至 Ollama，請先執行：ollama serve", file=sys.stderr)
                sys.exit(1)
            print(f"[警告] 連線失敗（嘗試 {attempt + 1}）：{e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[警告] HTTP {e.code}（嘗試 {attempt + 1}）：{body}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="逐段翻譯字幕（Ollama 本地模型）")
    parser.add_argument("--input", "-i", required=True, help="輸入 JSON 檔路徑")
    parser.add_argument("--output", "-o", required=True, help="輸出 JSON 檔路徑")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama 模型名稱")
    args = parser.parse_args()

    segments = load_segments(args.input)
    seg_dicts = [{"index": s.index, "timestamp": s.timestamp, "text": s.text} for s in segments]
    total = len(seg_dicts)
    print(f"[資訊] 載入 {total} 段，使用模型：{args.model}", file=sys.stderr)

    # 斷點續傳：讀取既有進度
    progress_path = Path(args.output + ".progress.json")
    done: dict[int, str] = {}
    if progress_path.exists():
        with open(progress_path, "r", encoding="utf-8") as f:
            raw: dict = json.load(f)
        done = {int(k): str(v) for k, v in raw.items()}
        print(f"[資訊] 讀取既有進度：已完成 {len(done)} 段", file=sys.stderr)

    # 逐段翻譯
    for i, seg in enumerate(seg_dicts, start=1):
        idx: int = int(seg["index"])
        if done.get(idx):
            continue  # 已有非空翻譯，略過

        translation = translate_one(args.model, seg["text"])
        done[idx] = translation

        # 每段完成後儲存進度
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump(done, f, ensure_ascii=False)

        status = "OK" if translation else "空白"
        print(f"[進度] {i}/{total}  [{status}]  {seg['timestamp']}", file=sys.stderr)

    # 組裝最終輸出
    output_data = []
    for seg in seg_dicts:
        idx = int(seg["index"])
        translation = done.get(idx, "")
        if not translation:
            print(f"[警告] 段 {idx} 無翻譯結果", file=sys.stderr)
        output_data.append({
            "index": idx,
            "timestamp": seg["timestamp"],
            "text": seg["text"],
            "translation": translation,
        })

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    translated_count = sum(1 for v in list(done.values()) if v)
    print(
        f"[完成] {translated_count}/{total} 段已翻譯，輸出：{args.output}",
        file=sys.stderr,
    )
    if translated_count < total:
        print(f"[警告] 尚有 {total - translated_count} 段未翻譯", file=sys.stderr)


if __name__ == "__main__":
    main()
