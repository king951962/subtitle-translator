"""共用模組：字幕資料結構、格式偵測、JSON 序列化輔助。"""

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

# --- 資料結構 ---

@dataclass
class SubtitleSegment:
    index: int
    timestamp: str
    text: str  # 可能含多行，以 \n 分隔


# --- 時間軸正則 ---

# SRT: 00:00:01,000 --> 00:00:04,000
SRT_TIMESTAMP_RE = re.compile(
    r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}"
)

# VTT: 00:00:01.000 --> 00:00:04.000 (小時可省略)
VTT_TIMESTAMP_RE = re.compile(
    r"(?:\d{2}:)?\d{2}:\d{2}\.\d{3}\s*-->\s*(?:\d{2}:)?\d{2}:\d{2}\.\d{3}"
)

# TXT: 同時匹配 SRT 或 VTT 風格的時間軸
ANY_TIMESTAMP_RE = re.compile(
    r"(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}"
)


# --- 格式偵測 ---

def detect_format(filepath: str) -> str:
    """偵測字幕格式，回傳 'srt'、'vtt' 或 'txt'。"""
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext == ".srt":
        return "srt"
    if ext == ".vtt":
        return "vtt"
    if ext == ".txt":
        # 進一步確認內容
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            if first_line.upper().startswith("WEBVTT"):
                return "vtt"
        except Exception:
            pass
        return "txt"

    # 未知副檔名，嘗試內容偵測
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            head = f.read(512)
        if head.strip().upper().startswith("WEBVTT"):
            return "vtt"
        if SRT_TIMESTAMP_RE.search(head):
            return "srt"
    except Exception:
        pass

    return "txt"


# --- JSON 序列化 ---

def segments_to_json(segments: List[SubtitleSegment]) -> str:
    """將 segments 序列化為 JSON 字串。"""
    return json.dumps(
        [asdict(s) for s in segments], ensure_ascii=False, indent=2
    )


def segments_from_json(json_str: str) -> List[SubtitleSegment]:
    """從 JSON 字串反序列化為 segments。"""
    data = json.loads(json_str)
    return [SubtitleSegment(**item) for item in data]


def save_segments(segments: List[SubtitleSegment], filepath: str) -> None:
    """將 segments 寫入 JSON 檔。"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(segments_to_json(segments))


def load_segments(filepath: str) -> List[SubtitleSegment]:
    """從 JSON 檔讀取 segments。"""
    with open(filepath, "r", encoding="utf-8") as f:
        return segments_from_json(f.read())
