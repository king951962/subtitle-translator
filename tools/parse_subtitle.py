"""解析 .srt / .vtt / .txt 字幕檔，輸出 JSON 格式。

用法：
    python tools/parse_subtitle.py <input_file> [--output <json_path>]

若省略 --output，JSON 輸出至 stdout。
"""

import argparse
import sys
import re
from pathlib import Path

# 讓 tools/ 下的模組可互相 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

from subtitle_utils import (
    SubtitleSegment,
    SRT_TIMESTAMP_RE,
    VTT_TIMESTAMP_RE,
    ANY_TIMESTAMP_RE,
    detect_format,
    segments_to_json,
    save_segments,
)


# --- SRT 解析 ---

def parse_srt(content: str) -> list[SubtitleSegment]:
    """解析 SRT 格式字幕。"""
    segments: list[SubtitleSegment] = []
    # 以空行分割區塊
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue

        # 找到時間軸行
        ts_line_idx = None
        for i, line in enumerate(lines):
            if SRT_TIMESTAMP_RE.search(line):
                ts_line_idx = i
                break

        if ts_line_idx is None:
            continue

        # index 在時間軸行之前（通常是第一行）
        try:
            index = int(lines[0].strip()) if ts_line_idx > 0 else len(segments) + 1
        except ValueError:
            index = len(segments) + 1

        timestamp = lines[ts_line_idx].strip()
        text_lines = lines[ts_line_idx + 1:]
        text = "\n".join(text_lines).strip()

        if not text:
            print(f"[警告] 區塊 {index} 文字為空", file=sys.stderr)

        segments.append(SubtitleSegment(index=index, timestamp=timestamp, text=text))

    return segments


# --- VTT 解析 ---

def parse_vtt(content: str) -> list[SubtitleSegment]:
    """解析 WebVTT 格式字幕。"""
    segments: list[SubtitleSegment] = []

    # 移除 WEBVTT 標頭與 NOTE / STYLE 區塊
    lines = content.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("WEBVTT"):
            start = i + 1
            break

    # 跳過標頭後的空行與 metadata
    body = "\n".join(lines[start:])
    blocks = re.split(r"\n\s*\n", body.strip())

    index_counter = 0
    for block in blocks:
        block_lines = block.strip().splitlines()
        if not block_lines:
            continue

        # 跳過 NOTE 與 STYLE 區塊
        first = block_lines[0].strip().upper()
        if first.startswith("NOTE") or first.startswith("STYLE"):
            continue

        # 找到時間軸行
        ts_line_idx = None
        for i, line in enumerate(block_lines):
            if VTT_TIMESTAMP_RE.search(line):
                ts_line_idx = i
                break

        if ts_line_idx is None:
            continue

        index_counter += 1
        timestamp = block_lines[ts_line_idx].strip()
        text_lines = block_lines[ts_line_idx + 1:]
        text = "\n".join(text_lines).strip()

        if not text:
            print(f"[警告] 區塊 {index_counter} 文字為空", file=sys.stderr)

        segments.append(SubtitleSegment(
            index=index_counter, timestamp=timestamp, text=text
        ))

    return segments


# --- TXT 解析 ---

def parse_txt(content: str) -> list[SubtitleSegment]:
    """解析 .txt 格式字幕（時間軸行 + 文字行交替）。"""
    segments: list[SubtitleSegment] = []
    lines = content.strip().splitlines()

    index_counter = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # 嘗試匹配時間軸
        ts_match = ANY_TIMESTAMP_RE.search(line)
        if ts_match:
            timestamp = ts_match.group(0)
            # 先取時間軸之後同一行的文字（如 [ts]  text 格式）
            inline_text = line[ts_match.end():].strip().lstrip("]").strip()
            # 再收集後續非時間軸行作為文字
            text_lines = [inline_text] if inline_text else []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    i += 1
                    break
                if ANY_TIMESTAMP_RE.search(next_line):
                    break
                text_lines.append(next_line)
                i += 1

            index_counter += 1
            text = "\n".join(text_lines).strip()

            if not text:
                print(f"[警告] 區塊 {index_counter} 文字為空", file=sys.stderr)

            segments.append(SubtitleSegment(
                index=index_counter, timestamp=timestamp, text=text
            ))
        else:
            # 非時間軸行，跳過
            i += 1

    return segments


# --- 主程式 ---

def main():
    parser = argparse.ArgumentParser(description="解析字幕檔為 JSON 格式")
    parser.add_argument("input_file", help="輸入字幕檔路徑（.srt / .vtt / .txt）")
    parser.add_argument("--output", "-o", help="輸出 JSON 檔路徑（預設為 stdout）")
    args = parser.parse_args()

    input_path = args.input_file
    if not Path(input_path).exists():
        print(f"[錯誤] 找不到檔案：{input_path}", file=sys.stderr)
        sys.exit(1)

    # 讀取檔案
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 偵測格式並解析
    fmt = detect_format(input_path)
    print(f"[資訊] 偵測格式：{fmt}", file=sys.stderr)

    if fmt == "srt":
        segments = parse_srt(content)
    elif fmt == "vtt":
        segments = parse_vtt(content)
    else:
        segments = parse_txt(content)

    print(f"[資訊] 解析完成，共 {len(segments)} 段", file=sys.stderr)

    # 時間軸順序檢查（僅警告）
    for i in range(1, len(segments)):
        prev_ts = segments[i - 1].timestamp
        curr_ts = segments[i].timestamp
        if curr_ts < prev_ts:
            print(
                f"[警告] 時間軸可能亂序：段 {segments[i].index} ({curr_ts}) < 段 {segments[i-1].index} ({prev_ts})",
                file=sys.stderr,
            )

    # 輸出
    if args.output:
        save_segments(segments, args.output)
        print(f"[資訊] JSON 已寫入：{args.output}", file=sys.stderr)
    else:
        print(segments_to_json(segments))


if __name__ == "__main__":
    main()
