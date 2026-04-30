# YouTube 字幕自動翻譯系統

將英文 YouTube 字幕自動翻譯為繁體中文，輸出中英對照格式，本地執行、零 API 費用。

---

## 解決的問題

追蹤 Karpathy 等 AI 技術 YouTuber 時，面臨三個痛點：

- 影片全英文，10 小時以上的完整課程
- YouTube 自動字幕品質差、有延遲、翻譯不準
- 沒有官方中文版，也沒有等待的理由

**我的反應不是忍耐，而是做一個工具解決它。**

---

## 系統架構：WAT 三層設計

本專案採用 **WAT（Workflows → Agents → Tools）** 架構，將職責明確分離：

```
┌─────────────────────────────────────────────┐
│  Workflows（workflows/*.md）                 │
│  SOP 文件：定義做什麼、怎麼做、邊界案例處理   │
└────────────────────┬────────────────────────┘
                     ↓
┌─────────────────────────────────────────────┐
│  Agent（Claude Code）                        │
│  讀取 Workflow → 協調工具 → 處理錯誤          │
│  → 從失敗中學習並更新 Workflow               │
└────────────────────┬────────────────────────┘
                     ↓
┌─────────────────────────────────────────────┐
│  Tools（tools/*.py）                         │
│  確定性執行：解析、翻譯、格式化、品質檢查      │
└─────────────────────────────────────────────┘
```

**為什麼這樣設計？**

AI 直接串連每個步驟，若每步準確率 90%，五步後成功率只剩 59%。
把執行交給確定性腳本，AI 只負責協調判斷，整體系統可靠性大幅提升。

---

## 翻譯流程

```
輸入（.srt / .vtt / .txt）
    ↓ parse_subtitle.py
解析為結構化 JSON
    ↓ translate_segments.py（本地 Ollama gemma3:12b）
逐段翻譯，支援斷點續傳
    ↓ format_output.py
格式化為中英對照 VTT
    ↓ check_translation_quality.py
5 維品質自動檢核
    ↓
輸出（_translated.vtt + 品質報告）
```

---

## 輸出格式範例

輸入（英文 SRT）：

```
1
00:00:08,160 --> 00:00:13,600
What I'd like to do is build something like ChatGPT from scratch.
```

輸出（中英對照 VTT）：

```
00:00:08.160 --> 00:00:13.600
我想做的是從零開始建立一個類似 ChatGPT 的東西。
What I'd like to do is build something like ChatGPT from scratch.
```

完整範例見 [`examples/`](examples/) 目錄。

---

## 品質控制：5 個自動檢核維度

| 維度 | 說明 |
|------|------|
| 殘留英文 | 譯文中長英文單字比例過高（> 20%） |
| 亂碼偵測 | 日文假名混入、LLM markdown 格式幻覺 |
| 簡體字混入 | 目標語言為繁體中文，自動標記偏差 |
| 未翻譯段落 | 空白譯文或譯文與原文完全相同 |
| 長度異常 | 譯文長度比例異常（> 2x 或 < 15%），疑似截斷或幻覺 |

翻譯完成後自動產出品質報告（`output/*_quality_report.txt`），標記所有問題段落供人工複查。

---

## 快速開始

### 前置需求

```bash
# 安裝 Ollama 並下載模型
ollama pull gemma3:12b

# 安裝 Python 依賴
pip install -r requirements.txt
```

### 一行指令翻譯

```bash
python tools/run.py "input/your_subtitle.srt"
```

輸出至 `output/<slug>_translated.vtt`，品質報告至 `output/<slug>_quality_report.txt`。

### 指定模型（VRAM 不足時）

```bash
python tools/run.py "input/your_subtitle.srt" --model qwen2.5:7b
```

### 手動分步執行

```bash
# 步驟 1：解析
python tools/parse_subtitle.py "input/file.srt" --output ".tmp/slug/parsed.json"

# 步驟 2：翻譯（支援中斷後續傳）
python tools/translate_segments.py --input ".tmp/slug/parsed.json" --output ".tmp/slug/translated.json"

# 步驟 3：格式化輸出
python tools/format_output.py --input ".tmp/slug/translated.json" --output "output/result.vtt"

# 步驟 4：品質檢查
python tools/check_translation_quality.py --input "output/result.vtt"
```

---

## 成果

| 項目 | 數字 |
|------|------|
| 翻譯影片數 | 13 部 |
| 總內容時長 | 25+ 小時 |
| 最長單部課程 | 10 小時 |
| 翻譯費用 | $0（本地模型） |
| 品質檢核維度 | 5 個 |

---

## 工具清單

| 檔案 | 功能 |
|------|------|
| `tools/run.py` | 一鍵執行完整流程 |
| `tools/parse_subtitle.py` | 解析 SRT / VTT / TXT |
| `tools/translate_segments.py` | 呼叫 Ollama 逐段翻譯，支援斷點續傳 |
| `tools/format_output.py` | 輸出中英對照 VTT |
| `tools/check_translation_quality.py` | 5 維品質自動檢核 |
| `tools/fix_hallucinations.py` | 偵測並修復 LLM 幻覺段落 |
| `tools/improve_translations.py` | 對低品質段落二次翻譯 |
| `workflows/translate_subtitle.md` | 完整 SOP 文件 |

---

## 設計原則

1. **確定性優先**：解析、格式化、品質檢查由 Python 腳本處理，結果可重現
2. **自我改進迴圈**：每次發現問題 → 修正工具 → 更新 Workflow 文件 → 下次不重蹈
3. **斷點續傳**：`.progress.json` 記錄翻譯進度，大型影片中途中斷可無縫續傳
4. **成本優化**：預設使用本地 Ollama，不依賴付費 API

---

## 支援格式

| 輸入 | 輸出 |
|------|------|
| `.srt`（SubRip） | `.vtt`（WebVTT，中英對照） |
| `.vtt`（WebVTT） | `_quality_report.txt`（品質報告） |
| `.txt`（YouTube 匯出） | |
