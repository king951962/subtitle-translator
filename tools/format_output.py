"""將翻譯結果格式化為最終 VTT 字幕檔（逐句對齊：中文 + 原文）。

用法：
    python tools/format_output.py --input <json> --output <vtt_path>

輸出格式（每區塊）：
    <timestamp>
    <第一行中文譯文>
    <第二行中文譯文（若有）>
    <第一行原始外文>
    <第二行原始外文（若有）>
"""

import argparse
import json
import re
import sys
from pathlib import Path


def srt_ts_to_vtt(timestamp: str) -> str:
    """將 SRT 時間軸格式（逗號）轉換為 VTT 格式（點）。
    例：00:00:01,000 --> 00:00:04,000 → 00:00:01.000 --> 00:00:04.000
    """
    return timestamp.replace(",", ".")


def align_lines(trans: list[str], orig_count: int) -> list[str]:
    """調整譯文行數使其與原文一致（逐句對齊）。"""
    result: list[str] = list(trans)
    if len(result) < orig_count:
        result.extend([""] * (orig_count - len(result)))
    elif len(result) > orig_count:
        front = [result[i] for i in range(orig_count - 1)]
        tail = [result[i] for i in range(orig_count - 1, len(result))]
        return front + ["".join(tail)]
    return result


def format_segments(data: list[dict]) -> str:
    """將翻譯資料格式化為 VTT 字串（逐句對齊）。"""
    blocks = []

    for seg in data:
        timestamp = srt_ts_to_vtt(seg["timestamp"])
        original_lines: list[str] = seg["text"].split("\n")
        translation: str = seg.get("translation") or ""
        translation_lines: list[str] = translation.split("\n") if translation else []

        translation_lines = align_lines(translation_lines, len(original_lines))

        # 組裝區塊：timestamp → 中文行 → 原文行（VTT 不需要 index 行）
        lines: list[str] = [timestamp] + translation_lines + original_lines
        blocks.append("\n".join(lines))

    # VTT 檔案以 WEBVTT 標頭開始
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def main():
    parser = argparse.ArgumentParser(description="格式化翻譯結果為 VTT 字幕檔")
    parser.add_argument("--input", "-i", required=True, help="翻譯結果 JSON 檔路徑")
    parser.add_argument("--output", "-o", required=True, help="輸出 VTT 檔路徑")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"[錯誤] 找不到檔案：{args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"[資訊] 載入 {len(data)} 段翻譯結果", file=sys.stderr)

    result = format_segments(data)

    # 確保輸出目錄存在
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(result)

    # 驗證逐句對齊
    misaligned = []
    for seg in data:
        orig_count = len(seg["text"].split("\n"))
        trans = seg.get("translation", "")
        trans_count = len(trans.split("\n")) if trans else 0
        if orig_count != trans_count and trans:
            misaligned.append(seg["index"])

    if misaligned:
        print(
            f"[警告] 以下段落行數不一致（已自動調整）：{misaligned}",
            file=sys.stderr,
        )

    print(f"[資訊] VTT 檔已寫入：{args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
