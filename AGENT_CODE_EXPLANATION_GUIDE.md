# AI Agent：新增程式碼解釋到知識庫

本文件給**外部 AI Coding Agent**使用。Agent 在自己的工作環境讀取 Repository、追蹤程式碼與 SQL、產生解釋，最後透過本系統 API 保存。知識庫網站只提供瀏覽、搜尋及 API，**不會替 Agent 讀檔、分析或呼叫 LLM**。

完整端點清單見 [AGENT_API.md](AGENT_API.md)。以下是新增一筆 CODE 解釋時應實際執行的順序。

## 1. 連線與權限

| 環境 | API Base |
| --- | --- |
| `start.bat` 本機啟動 | `http://127.0.0.1:5000/api` |
| PythonAnywhere 掛載 | `https://<host>/codeknowledge/api` |

每個 Agent API 請求都帶：

```http
Authorization: Bearer <CODEKNOWLEDGE_API_TOKEN>
Content-Type: application/json
```

本機 Token 位於未提交 Git 的 `instance/local_settings.json`，欄位是 `api_token`。正式環境由部署設定提供。**不要把 Token 寫進分析內容、程式碼片段、Markdown 範例或日誌。** `CODEKNOWLEDGE_USER_NOTE_TOKEN` 專供使用者筆記 API；Agent 不應取得或使用。

API 成功回應形狀：

```json
{"success": true, "data": {"id": 123}, "error": null}
```

失敗回應形狀：

```json
{"success": false, "data": null, "error": "錯誤原因"}
```

每次呼叫都檢查 HTTP 狀態碼與 `success`，不要只憑請求已送出就認為保存成功。

## 2. 在外部完成原始碼分析

Agent 應自行讀取使用者指定的 Repository。對指定檔案、Class、Method 或行範圍，整理：

1. 來源檔案的**相對路徑**、語言、Symbol 名稱、起訖行號與實際程式碼片段。
2. 呼叫鏈與關聯檔案；例如 Controller → Service → Mapper → SQL。只記錄有來源依據的關係。
3. **技術說明**：輸入、主要判斷、呼叫、資料變更、輸出與錯誤處理。
4. **業務說明**：這段程式在實際流程中的目的。若只能從程式碼推測，清楚標示為推測。
5. SQL 的原文、類型、用途、資料表引用與業務意義。
   同時整理 Mapper、ORM、Repository 與程式碼直接使用的資料表，和 SQL 使用的表分別建立引用。
6. 如有助理解，產生 Mermaid `flowchart` 原始碼。

`source_code` 應取自實際檔案，不要憑空重寫。`start_line`、`end_line` 使用來源檔案的行號，且結束行不得小於起始行。若來源含真實密鑰或個資，先依使用者的資料處理要求處理，不要把秘密放進知識庫。

## 3. 先查既有分類與分析

先呼叫：

```http
GET /api/agent/context
```

回傳 `data.projects[]`，每個 Project 含 `categories[]`，每個 Category 含 `features[]`。找到目標 Project 後，再呼叫：

```http
GET /api/agent/context/{project_id}
```

這個回應的 `data.project` 是 Project；`data.categories[]` 包含 Feature 以及其 `analyses[]` 摘要。優先使用名稱與含義相同的既有分類。例如已有 `Production Report`，就不要另外建立 `Production Reporting`。

只有確定不存在時才逐層建立：

```http
POST /api/projects
{"name":"KTG-MES","description":"MES 知識庫"}

POST /api/categories
{"project_id":1,"name":"Production","description":"生產管理"}

POST /api/features
{"category_id":10,"name":"Production Report","description":"生產回報"}
```

從每次成功回應的 `data.id` 取得下一層的 ID。若收到重複名稱錯誤，重新讀取 Context 並使用已存在的項目，不要改個近似名稱重試。

同一 Feature 下，呼叫 `GET /api/analyses?feature_id={feature_id}`，比對 `file_path`、`symbol_name`、`start_line`、`end_line` 和分析目的。若找到相同對象，使用 `GET /api/analyses/{id}` 查看完整內容，再選擇更新；不要無條件新增。API 目前沒有分析建立的冪等鍵，所以這一步是避免重複資料的必要檢查。

## 4. 準備 Analysis JSON

下例是**示意資料，不代表已分析真實 Repository**：

```json
{
  "feature_id": 100,
  "title": "ProductionReportController.report()",
  "file_path": "src/main/java/com/example/ProductionReportController.java",
  "symbol_name": "report",
  "symbol_type": "method",
  "start_line": 80,
  "end_line": 92,
  "language": "java",
  "source_code": "public ReportResult report(ReportRequest request) {\n    return reportService.save(request);\n}",
  "technical_explanation": "接收報工請求，呼叫 reportService.save，並回傳保存結果。實際驗證及交易行為需依 Service 原始碼確認。",
  "business_explanation": "讓現場提交生產回報，供 MES 記錄產量。",
  "tables": [{"table_name": "mes_production_report", "usage_note": "Repository 對應報工主檔"}],
  "flow_source": "flowchart TD\nController[Controller.report] --> Service[Service.save]",
  "analysis_status": "reviewed"
}
```

| 欄位 | 規則 |
| --- | --- |
| `feature_id` | 必填，必須指向既有 Feature。系統由此推得 `project_id`、`category_id`。 |
| `title` | 必填，1–200 字元。建議能區分檔案與方法。 |
| `file_path` | Repository 內的來源路徑；只作知識顯示，本站不會讀取它。 |
| `symbol_name` | Class、Method、Function 或其他被解釋的 Symbol 名稱。 |
| `symbol_type` | `class`、`method`、`function`、`controller`、`service`、`mapper`、`repository`、`component`、`sql`、`other`。 |
| `start_line`、`end_line` | 可省略；若提供，從 1 開始且 `end_line >= start_line`。 |
| `language` | Code Viewer 使用的語言，例如 `java`、`python`、`csharp`、`javascript`、`typescript`、`sql`。 |
| `source_code` | 要展示的原始程式碼；SQL 也可另外放入 SQL Snippet。 |
| `technical_explanation` | 技術行為及有來源依據的結論。 |
| `business_explanation` | 對使用者或業務流程的意義。 |
| `flow_source` | 可省略；有值時應是可渲染的 Mermaid 原始碼。 |
| `tables` | 程式碼／Mapper／ORM 使用的資料表清單；每筆可寫 `table_name` 與 `usage_note`。SQL 的表另放在 SQL Snippet。 |
| `analysis_status` | `draft` 或 `reviewed`；預設 `draft`。 |

撰寫 `technical_explanation`、`business_explanation`、SQL 說明與筆記時，請在不同段落之間放入實際換行（JSON 中使用 `\n`），尤其不要把 `1.`、`2.` 等步驟直接接在前一句後面。`flow_source` 請只放 Mermaid 原始碼，並以實際換行分隔每一條語句。

不要在一般 Analysis JSON 送 `user_note`：它屬使用者，Agent 更新時即使送出也會被忽略。`created_by` 由 API 設為 `AI`，不必送。若送 `project_id` 或 `category_id`，必須與 `feature_id` 的實際階層一致。

## 5. 預覽、使用者確認、保存

先把第 4 節的 JSON 送到：

```http
POST /api/analyses/preview
```

成功時回傳正規化欄位，**不會建立 Analysis**。Agent 應向使用者展示程式碼、技術解釋、業務解釋、SQL 與關聯依據。使用者要求修改時，先修改內容並再次預覽；取消時不要呼叫寫入 API。

確認後，對同一筆 Analysis JSON 加上布林值 `"confirmed": true`，呼叫：

```http
POST /api/analyses
```

成功狀態碼為 `201`，回傳 `data.id`、原始碼、解釋與關聯欄位。記下 `analysis_id`，後續 SQL 與關聯資料需要它。`confirmed=true` 是 **Agent 對已完成使用者確認的聲明**；伺服器目前不維護人工審批佇列，Agent 不能自行略過使用者確認。

若第 3 節已找到同一筆分析，使用：

```http
PATCH /api/analyses/{analysis_id}
{"technical_explanation":"更新後的解釋","confirmed":true}
```

PATCH 可只送需要變更的欄位。更新前仍應讓使用者確認，並保留既有的 `user_note`。

## 6. 另存 SQL、資料表與關聯

若有資料表說明檔，先按 Project 與表名查 `GET /api/database-tables?project_id={project_id}`。讀取原檔後將欄位名稱、型態、中文說明及備註整理成 Markdown 表格，包含有來源依據的公式或算式，再以 `POST /api/database-tables` 保存；已存在時同一端點會更新共用說明。不要為同一張表建立多份說明。分析 JSON 的 `tables` 提供程式使用的引用；以下 SQL Snippet 的 `tables` 提供 SQL 使用的引用。兩者都會連到同一張資料表說明頁。

先呼叫 `GET /api/analyses/{analysis_id}` 檢查既有 `sql_snippets[]`，避免重複新增相同 SQL。確認後，使用：

```http
POST /api/sql
Content-Type: application/json

{
  "analysis_id": 200,
  "title": "依 ID 查詢報工資料",
  "sql_type": "SELECT",
  "sql_code": "SELECT * FROM mes_production_report WHERE id = ?",
  "explanation": "以參數化條件查詢一筆報工資料。",
  "business_explanation": "取得指定報工紀錄供畫面顯示。",
  "tables": [
    {"table_name": "mes_production_report", "description": "報工主檔"}
  ],
  "confirmed": true
}
```

`sql_type` 可為 `SELECT`、`INSERT`、`UPDATE`、`DELETE`、`MERGE`、`PROCEDURE`、`FUNCTION`、`OTHER`。`tables` 也可使用字串陣列，例如 `["mes_production_report"]`。本站**只保存 SQL 文字，不執行它**。目前 SQL API 提供新增與查詢；需要修正既有 SQL 時，先確認處理方式，避免建立混淆的重複片段。

關聯檔案：

```http
POST /api/analyses/{analysis_id}/related-files
{"file_path":"src/main/java/com/example/ProductionReportService.java","description":"Controller 呼叫的 Service","confirmed":true}
```

關聯分析：

```http
POST /api/analyses/{analysis_id}/relations
{"related_analysis_id":201,"relation_type":"calls","confirmed":true}
```

只有已存在的目標 Analysis 可建立關聯；同一筆 Analysis 不能關聯自己。關聯檔案與分析前也先檢查 `GET /api/analyses/{analysis_id}` 的既有清單。

## 7. 驗證並回報結果

保存後再次呼叫：

```http
GET /api/analyses/{analysis_id}
```

確認 `source_code`、解釋、`flow_source`、`sql_snippets`、資料表和關聯資料都正確。使用者也可在網站從 Project → Category → Feature → Analysis 瀏覽；本機網址為 `http://127.0.0.1:5000/knowledge/{analysis_id}`，掛載後需加上 `/codeknowledge` 前綴。

若需要全域確認是否已有類似知識，可用 `GET /api/search?q=<關鍵字>`；搜尋涵蓋分類、分析、檔案路徑、程式碼、說明、筆記和 SQL。

## 錯誤處理

| 狀態 | Agent 應採取的動作 |
| --- | --- |
| `400` | 檢查欄位、Feature ID、行號、列舉值與 `confirmed=true`；不要反覆送相同資料。 |
| `401` | Agent Token 缺失或錯誤；向執行環境取得正確 Token，不要要求使用者把 Token 放進分析內容。 |
| `409` | 關聯或資料表引用可能重複；重新取得 Analysis 與 Context 後決定是否略過。 |
| `413` | 請求超過 2 MiB；縮小程式碼範圍或拆成多筆有意義的 Analysis。 |

分類與功能建立遇到重複名稱時目前通常回 `400`，應重新查 Context。網路超時後不要立刻重送 `POST /api/analyses`，先查列表，因為前一次請求可能已保存成功。
