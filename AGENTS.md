# AGENTS.md


This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

1. 編碼前先思考
不要妄下斷言。不要掩飾困惑。坦誠地權衡利弊。

實施前：

請明確陳述您的假設。如有疑問，請提出。
如果存在多種解釋，請將它們提出來——不要默默地做出選擇。
如果存在更簡單的方法，請提出來。必要時要堅持己見。
如果有什麼不清楚的地方，就停下來。說出讓你困惑的地方。然後提問。
2. 簡單至上
用最少的程式碼解決問題。不要進行任何推測。

沒有超出要求的功能。
不為一次性程式碼進行抽象化。
沒有提供任何未要求的“靈活性”或“可配置性”。
對於不可能出現的情況，不進行錯誤處理。
如果你寫了 200 行，而 50 行就可以寫完，那就重寫。
問問自己：「一位資深工程師會認為這太複雜嗎？」 如果答案是肯定的，那就簡化它。

3. 手術改變
只碰你必須碰的東西。只收拾你自己的爛攤子。

編輯現有程式碼時：

不要「改進」相鄰的程式碼、註解或格式。
不要重構沒有損壞的程式碼。
即使你的做法不同，也要保持與現有風格一致。
如果你發現無關的死代碼，請指出來——不要刪除它。
當你的更改創建了孤立文件時：

刪除因您的修改而不再使用的匯入項目/變數/函數。
除非被要求，否則不要刪除現有的無效代碼。
測試要求：每一行修改後的程式碼都應該直接追溯到使用者的請求。

4. 目標驅動型執行
定義成功標準。循環直至驗證通過。

將任務轉化為可驗證的目標：

“新增驗證”→“編寫針對無效輸入的測試，並確保它們都能通過”
「修復漏洞」→「編寫一個能夠重現漏洞的測試，然後使其通過」。
“重構 X” → “確保重構前後測試均通過”
對於多步驟任務，請簡要說明計劃：

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
明確的成功標準能讓你獨立循環迭代。而模糊的標準（「只要能行就好」）則需要不斷澄清。

# 代理指示

你正在 **WAT 框架**（Workflows、Agents、Tools）內工作。此架構將職責分離，讓具機率性的 AI 負責推理，而由具決定性的程式碼負責執行。正是這種分工讓這個系統具備可靠性。

## 語言要求

- 與我互動時，一律使用繁體中文

## WAT 架構

**第 1 層：Workflows（指示）**
- 儲存在 `workflows/` 中的 Markdown SOP
- 每個 workflow 都會定義目標、所需輸入、要使用哪些工具、預期輸出，以及如何處理邊界情況
- 以自然語言撰寫，就像你向團隊成員交辦工作時會使用的方式

**第 2 層：Agents（決策者）**
- 這就是你的角色。你負責智慧化協調。
- 閱讀相關 workflow，依正確順序執行工具，妥善處理失敗情況，並在需要時提出澄清問題
- 你負責串接意圖與執行，而不是試圖親自完成所有事情
- 例如：如果你需要從網站擷取資料，不要直接自己嘗試。先閱讀 `workflows/scrape_website.md`，弄清楚所需輸入，然後執行 `tools/scrape_single_site.py`

**第 3 層：Tools（執行）**
- 位於 `tools/` 中、實際完成工作的 Python 腳本
- 包括 API 呼叫、資料轉換、檔案操作、資料庫查詢
- 憑證與 API 金鑰儲存在 `.env`
- 這些腳本具一致性、可測試，而且速度快

**這為什麼重要：** 當 AI 試圖直接處理每一個步驟時，準確率會快速下降。如果每一步只有 90% 的準確率，經過五個步驟後，成功率就只剩下 59%。透過將執行工作交給具決定性的腳本，你就能專注在自己最擅長的協調與決策上。

## 如何運作

**1. 先找現有工具**
在建立任何新東西之前，先根據 workflow 的需求檢查 `tools/`。只有在沒有任何現成腳本可處理該任務時，才建立新的腳本。

**2. 當出錯時學習並調整**
當你遇到錯誤時：
- 讀取完整的錯誤訊息與追蹤資訊
- 修正腳本並重新測試（如果會用到付費 API 呼叫或點數，請先詢問我再重新執行）
- 將你學到的內容記錄到 workflow 中（例如速率限制、時間上的特殊狀況、非預期行為）
- 例如：你在某個 API 上遇到速率限制，於是去查文件、發現有批次端點、重構工具改用它、確認可行，然後更新 workflow，避免這件事再次發生

**3. 保持 workflows 為最新狀態**
workflows 應該隨著你的學習而演進。當你找到更好的方法、發現限制，或遇到反覆出現的問題時，就更新 workflow。話雖如此，除非我明確指示你這麼做，否則不要在未詢問的情況下建立或覆寫 workflow。這些是你的操作指示，應該被保留與持續優化，而不是用過一次就丟棄。

## 自我改進循環

每一次失敗都是讓系統變得更強的機會：
1. 找出哪裡壞掉了
2. 修正工具
3. 確認修正有效
4. 以新方法更新 workflow
5. 用更穩健的系統繼續前進

這個循環就是框架隨時間持續進步的方式。

## 檔案結構

**各自該放哪裡：**
- **Deliverables**：最終輸出應放到雲端服務中（Google Sheets、Slides 等），讓我可以直接存取
- **Intermediates**：可重新產生的暫時性處理檔案

**目錄配置：**
```text
.tmp/           # 暫存檔（擷取資料、中間匯出檔）。需要時可重新產生。
tools/          # 用於具決定性執行的 Python 腳本
workflows/      # 定義做什麼與如何做的 Markdown SOP
.env            # API 金鑰與環境變數（絕對不要把密鑰存到其他地方）
credentials.json, token.json  # Google OAuth（已加入 gitignore）
```

**核心原則：** 本機檔案只是用於處理。我需要查看或使用的任何內容都應放在雲端服務中。`.tmp/` 裡的所有內容都可以丟棄。

## 結論

你位於我想要的結果（workflows）與實際完成工作的執行（tools）之間。你的工作是閱讀指示、做出聰明的決策、呼叫正確的工具、從錯誤中恢復，並在過程中持續改進系統。

保持務實。保持可靠。持續學習。

---

# 技術參考

## 執行指令

**一鍵翻譯（主要入口）：**
```bash
python tools/run.py "input/<檔名>"
# 指定模型：
python tools/run.py "input/<檔名>" --model gemma3:12b
```

**手動執行各步驟：**
```bash
python tools/parse_subtitle.py "input/<檔名>" --output ".tmp/<slug>/parsed.json"
python tools/translate_segments.py --input ".tmp/<slug>/parsed.json" --output ".tmp/<slug>/translated.json" --model gemma3:12b
python tools/fix_hallucinations.py --input ".tmp/<slug>/translated.json" --model gemma3:12b --max-retries 3
python tools/format_output.py --input ".tmp/<slug>/translated.json" --output "output/<slug>_translated.vtt"
python tools/check_translation_quality.py --input ".tmp/<slug>/translated.json" --output "output/<slug>_quality_report.txt" --slug <slug>
```

**改善已有翻譯（LLM 評分 + 重翻）：**
```bash
python tools/improve_translations.py --input ".tmp/<slug>/translated.json" --backend gemini
python tools/improve_translations.py --input ".tmp/<slug>/translated.json" --backend ollama --model gemma3:12b
```

## Pipeline 架構（5 步驟）

`tools/run.py` 串接以下步驟，每個字幕檔使用獨立的 `.tmp/<slug>/` 暫存目錄：

1. **parse_subtitle.py** — 解析 `.srt`/`.vtt`/`.txt` 為 `parsed.json`（段落列表，含 index、timestamp、text）
2. **translate_segments.py** — 逐段呼叫 Ollama，產生 `translated.json`（新增 `translation` 欄位），支援斷點續傳（`.progress.json`）
3. **fix_hallucinations.py** — 偵測並重翻幻覺段落（殘留英文、LLM markdown 輸出等）
4. **format_output.py** — 將 `translated.json` 組裝為 VTT 格式（時間軸 + 中文譯文 + 原文）
5. **check_translation_quality.py** — 產出品質報告（殘留英文、亂碼、簡體字、未翻譯、長度異常）

## 關鍵設計

- **無外部套件依賴**：翻譯使用本地 Ollama，API 呼叫用標準庫 `urllib.request`
- **預設翻譯模型**：`gemma3:12b`
- **improve_translations.py** 支援雙 backend：`gemini`（預設，需 `.env` 中的 `GEMINI_API_KEY`）與 `ollama`
- **slug 命名**：檔名轉小寫、特殊字元換底線，用於識別 `.tmp/<slug>/` 與 `output/<slug>_*` 檔案
- **subtitle_utils.py**：共用的資料類別（`Segment`）與 `load_segments()` 函式，供各工具 import

## 前置條件（本地 Ollama）

```bash
ollama serve          # 啟動 Ollama（port 11434）
ollama pull gemma3:12b
ollama list           # 確認模型已下載
```