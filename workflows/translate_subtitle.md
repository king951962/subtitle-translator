# 字幕翻譯工作流程

## 目標
將外文字幕檔翻譯為繁體中文，輸出格式為「時間軸 + 中文譯文 + 原文」的三層結構，中文與原文逐句對齊。

## 前置條件
- 安裝並啟動 Ollama：`ollama serve`
- 確認模型已下載：`ollama pull gemma3:12b`
- 驗證模型可用：`ollama list`（應看到 `gemma3:12b`）
- 注意：gemma3:12b 為預設翻譯模型，翻譯品質優於 qwen2.5:7b；VRAM 不足時會自動 offload 至 RAM

## 所需輸入
- 字幕檔路徑（支援 `.srt`、`.vtt`、`.txt`），放在 `input/` 目錄中

## 執行步驟（一鍵完成）

```bash
python tools/run.py "input/<檔名>"
```

- 自動為每個輸入檔建立獨立的 `.tmp/<slug>/` 暫存目錄，不同字幕不會互相污染
- 支援斷點續傳：中途中斷後重新執行，會從上次進度繼續
- 輸出至 `output/<slug>_translated.vtt`

若要指定模型：
```bash
python tools/run.py "input/<檔名>" --model qwen2.5:7b
```

## 進階：手動執行三步驟

若需要單獨執行某個步驟（如重新翻譯但不重新解析）：

```bash
# 步驟 1：解析字幕
python tools/parse_subtitle.py "input/<檔名>" --output ".tmp/<slug>/parsed.json"

# 步驟 2：翻譯
python tools/translate_segments.py --input ".tmp/<slug>/parsed.json" --output ".tmp/<slug>/translated.json" --model gemma3:12b

# 步驟 3：格式化輸出
python tools/format_output.py --input ".tmp/<slug>/translated.json" --output "output/<slug>_translated.vtt"
```

**重要**：手動執行時，每個字幕檔必須使用各自的 `.tmp/<slug>/` 子目錄，不要共用 `.tmp/` 根目錄的固定檔名。

### 步驟 4：品質檢查與回報結果

自動執行品質檢查，報告輸出至 `output/<slug>_quality_report.txt`。

檢查項目：
- **殘留英文**：譯文中長英文單字比例過高（> 20%，排除 ≤ 4 字元的縮寫）
- **亂碼**：日文假名混入、LLM 幻覺（markdown 格式輸出）
- **簡體中文**：譯文含簡體字（目標為繁體中文）
- **未翻譯**：空白譯文或譯文與原文完全相同
- **長度異常**：譯文長度與原文比例異常（> 2 倍或 < 15%），疑似 LLM 幻覺或截斷

回報內容：
- 告知用戶翻譯完成的段數
- 各類問題的段數摘要
- 若問題段落數量過多，建議用戶檢視品質報告
- 提供輸出檔路徑與品質報告路徑

## 輸出格式範例（VTT）

```
WEBVTT

00:00:01.000 --> 00:00:04.000
你好世界
Hello world

00:00:05.000 --> 00:00:09.000
歡迎來到這個頻道
感謝收看
Welcome to this channel
Thanks for watching
```

## 錯誤處理

| 情況 | 處理方式 |
|------|---------|
| 解析失敗（格式不明） | 檢查檔案編碼（應為 UTF-8），確認格式是否正確 |
| Ollama 未啟動 | 執行 `ollama serve`，確認 port 11434 可連線 |
| 模型未下載 | 執行 `ollama pull gemma3:12b` |
| 翻譯結果行數不一致 | `format_output.py` 會自動調整，但應檢查警告段落 |
| 暫存污染（翻譯內容來自其他影片） | 刪除對應的 `.tmp/<slug>/` 子目錄後重新執行 |

## 邊界情況
- **HTML 標籤**（VTT 中的 `<i>` `<b>`）：預設保留，翻譯時會傳給 LLM
- **說話者標籤**（`- Speaker:`）：作為文字一部分翻譯
- **音樂符號**（♪）：保留不翻譯
- **已是中文的段落**：系統提示詞會指示 LLM 保持原文不變
- **空段落**：解析時會警告，翻譯時跳過
