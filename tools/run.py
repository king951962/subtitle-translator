"""字幕翻譯主控腳本：一鍵串接解析 → 翻譯 → 輸出，每個字幕檔使用獨立的暫存目錄。

用法：
    python tools/run.py input/<檔名> [--model qwen2.5:7b]

範例：
    python tools/run.py "input/Let's build GPT.txt"
    python tools/run.py "input/My Video.srt" --model qwen2.5:7b
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def slugify(name: str) -> str:
    """將檔名轉為安全的目錄名稱（小寫、特殊字元換底線）。"""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def run_step(cmd: list[str], label: str) -> None:
    print(f"\n{'='*50}")
    print(f"[步驟] {label}")
    print(f"{'='*50}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\n[錯誤] 步驟失敗，中止執行：{label}", file=sys.stderr)
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="字幕翻譯主控腳本")
    parser.add_argument("input", help="輸入字幕檔路徑（支援 .srt / .vtt / .txt）")
    parser.add_argument("--model", default="gemma3:12b", help="Ollama 模型名稱（預設：gemma3:12b）")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    if not input_path.exists():
        print(f"[錯誤] 找不到輸入檔案：{input_path}", file=sys.stderr)
        sys.exit(1)

    # 為每個輸入檔建立獨立的暫存目錄
    slug = slugify(input_path.stem)
    tmp_dir = ROOT / ".tmp" / slug
    tmp_dir.mkdir(parents=True, exist_ok=True)

    parsed_json = tmp_dir / "parsed.json"
    translated_json = tmp_dir / "translated.json"
    output_vtt = ROOT / "output" / f"{slug}_translated.vtt"

    print(f"[資訊] 輸入檔：{input_path.name}")
    print(f"[資訊] 暫存目錄：.tmp/{slug}/")
    print(f"[資訊] 輸出檔：output/{slug}_translated.vtt")
    print(f"[資訊] 翻譯模型：{args.model}")

    # 步驟 1：解析
    run_step(
        [sys.executable, "tools/parse_subtitle.py", str(input_path), "--output", str(parsed_json)],
        "解析字幕",
    )

    # 步驟 2：翻譯
    run_step(
        [sys.executable, "tools/translate_segments.py",
         "--input", str(parsed_json),
         "--output", str(translated_json),
         "--model", args.model],
        f"翻譯（{args.model}）",
    )

    # 步驟 3：修復幻覺
    run_step(
        [sys.executable, "tools/fix_hallucinations.py",
         "--input", str(translated_json),
         "--model", args.model,
         "--max-retries", "3"],
        "修復幻覺翻譯",
    )

    # 步驟 4：格式化輸出
    run_step(
        [sys.executable, "tools/format_output.py",
         "--input", str(translated_json),
         "--output", str(output_vtt)],
        "格式化輸出",
    )

    # 步驟 5：翻譯品質報告
    report_path = ROOT / "output" / f"{slug}_quality_report.txt"
    run_step(
        [sys.executable, "tools/check_translation_quality.py",
         "--input", str(translated_json),
         "--output", str(report_path),
         "--slug", slug],
        "翻譯品質報告",
    )

    print(f"\n[完成] 字幕已輸出至：{output_vtt.relative_to(ROOT)}")
    print(f"[完成] 品質報告：{report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
