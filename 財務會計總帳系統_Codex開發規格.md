# 財務會計總帳系統（GL）— Codex 開發規格書

> 版本：1.0｜語言：繁體中文｜目的：建立可操作、可測試、可擴充的 Web 版會計系統。
>
> 本文件參考使用者提供的傳統會計系統照片之功能選單，**不是原系統原始規格或原始碼**。模糊選單與未證實功能不應宣稱與原系統完全一致。

## 0. 給 Codex 的執行指令

你是資深 Python/Flask 工程師兼會計系統架構師。請依本文件逐階段實作可運行的系統，不只生成畫面或假資料。開始前檢查現有專案結構與 README；如有使用者提供的《PythonAnywhere掛載式Flask專案設計規範.md》，先閱讀並遵循，若與本文件衝突，列出衝突並優先遵循既有專案的部署約束。若該檔案未提供，不得臆測其內容。

先產出開發計畫與檔案樹，再實作 Phase 1；完成後執行測試並回報已完成、未完成、執行方式與風險。禁止將所有 Phase 宣稱一次完成。每個 Phase 須有可執行的驗收結果。若會計政策未定，使用明確標示的 DEMO 假設，不自行宣稱符合特定地區法規。

## 1. 產品定位與範圍

- 產品名稱：GL Accounting Demo（財務會計總帳系統）。
- 核心目標：從會計科目 → 傳票 → 審核/過帳 → 分類帳/試算表 → 損益表/資產負債表。
- 主要使用者：會計人員、審核主管、財務主管、系統管理員。
- 第一版：單公司、單本位幣、單會計帳簿；幣別與金額精度可設定，但暫不實作外幣重估。
- 第一版不包含：完整 AR/AP、稅務申報、固定資產折舊引擎、採購/庫存/MES、銀行串接。保留擴充介面，不可假裝已實作。
- 成本表：第一版只針對有明確科目對應的已入帳成本彙總；不是製造成本分攤或工單成本計算。

## 2. 技術規格

- Python 3.11+、Flask、SQLAlchemy、Alembic/Flask-Migrate、SQLite。
- Flask Blueprint 模組化：`auth`、`accounts`、`periods`、`vouchers`、`posting`、`reports`、`admin`。
- 前端：Jinja2 + Bootstrap 5 + 原生 JavaScript；桌機優先，手機可讀。
- API：REST JSON `/api/v1/`，統一錯誤格式；OpenAPI 文件或可讀的 API 說明。
- 安全：Werkzeug 密碼雜湊、session/CSRF 防護、角色權限、伺服器端驗證、稽核日誌。
- 資料庫：SQLite 啟用 `PRAGMA foreign_keys=ON`、交易控制與適當索引；正式多人高併發部署可規劃 PostgreSQL。
- 金額：Python `Decimal`；資料庫以最小貨幣單位整數儲存（如 cents），禁止使用 float 做帳務運算。UI 可顯示 2 位小數；若本位幣設定為 0 位小數則依設定處理。
- 時間：業務日期用 `DATE`，稽核時間用 UTC timestamp；畫面顯示時區可設定。
- 不依賴外部付費 API，預設可本機運行。

## 3. 功能模組

### 3.1 登錄作業

1. **會計科目維護**：科目代碼、名稱、類型（Asset/Liability/Equity/Revenue/Expense）、父科目、啟用狀態、是否允許直接過帳、正常餘額方向、報表分類；不得刪除已被傳票使用的科目。
2. **傳票登錄**：日期、編號、摘要、來源、明細列（科目、摘要、借方、貸方）；支援新增、草稿修改、送審、核准、駁回、過帳、查詢。
3. **傳票查詢**：依期間、編號、狀態、科目、摘要篩選；分頁、排序、CSV 匯出。
4. **期初餘額**：以受控的期初傳票或期初分錄輸入，借貸須平衡且有稽核記錄。

### 3.2 報表作業（對應照片可辨識選單）

1. 現金簿：現金科目收支與逐筆餘額。
2. 日記簿：按日期/傳票編號列出已過帳分錄。
3. 日計表：指定日期之借貸發生額與科目彙總。
4. 分類帳：指定科目、期間之期初、借方、貸方、逐筆餘額、期末。
5. 試算表：指定截止日之各科目借方/貸方餘額及平衡檢查。
6. 損益表：收入、成本、費用、本期損益；期間查詢。
7. 資產負債表：資產、負債、權益與本期未結轉損益；截至日期查詢。
8. 營業成本表：按映射到成本類別的會計科目彙總已入帳成本，清楚標示為「簡化版」。
9. 費用分析表：按費用科目與月份比較；顯示金額、占比。
10. 財務分析表：至少營業利益率、淨利率、流動比率（若科目分類不足顯示「無法計算」，不可編造）。

所有報表僅讀取**已過帳**且屬於所選會計期間的分錄；需顯示條件、生成時間、金額單位，並提供 CSV 匯出與列印友善頁面。報表不應直接修改帳務。

### 3.3 維護作業

- 使用者/角色：Admin、Accountant、Approver、Viewer。
- 會計年度與期間：Open、Closed；Closed 禁止新增、修改或過帳該期分錄。
- 參數：公司名稱、本位幣、金額小數位、日期格式、報表科目映射。
- 稽核日誌：記錄登入、科目變更、傳票送審/核准/過帳/沖銷、期間關閉與開啟。
- 資料完整性檢查：孤兒分錄、借貸不平、重複過帳、無效科目、關閉期間異常。
- 備份/還原：管理員可產生資料庫備份；還原需明確確認、權限限制、保留操作紀錄。
- 不提供直接刪除正式已過帳資料的操作；照片中「清除資料」僅在 DEMO 模式支援重置示範資料，必須二次確認。

## 4. 資料模型（建議）

| 資料表 | 核心欄位 | 約束/用途 |
|---|---|---|
| `users` | id, username, password_hash, role, is_active | 唯一帳號 |
| `accounts` | id, code, name, type, parent_id, normal_side, postable, active, report_group | code 唯一；階層不得循環 |
| `fiscal_periods` | id, fiscal_year, period_no, start_date, end_date, status | 期間不可重疊 |
| `vouchers` | id, voucher_no, voucher_date, period_id, description, source_type, source_ref, status, created_by, approved_by, approved_at, posted_at, reversed_voucher_id | voucher_no 唯一；狀態機 |
| `voucher_lines` | id, voucher_id, line_no, account_id, description, debit_minor, credit_minor | 金額非負；每列僅能一側大於 0 |
| `ledger_entries` | id, voucher_line_id, voucher_id, account_id, entry_date, period_id, debit_minor, credit_minor | `voucher_line_id` 唯一，避免重複過帳 |
| `audit_logs` | id, actor_id, action, entity_type, entity_id, before_json, after_json, created_at | 不可透過一般 UI 修改 |
| `system_settings` | key, value_json | 受權限控管 |
| `report_mappings` | id, account_id, report_type, group_code, effective_from | 報表分類映射 |

注意：報表可直接以已過帳 `voucher_lines` 查詢，或由 `ledger_entries` 讀取，但**全系統必須選定單一權威過帳來源**，不可同時計算造成重複。此規格採 `ledger_entries` 為報表來源，過帳時由 voucher lines 原子性產生。

### 4.1 索引

- `vouchers(voucher_date, status)`、`vouchers(period_id, status)`。
- `voucher_lines(voucher_id, line_no)`、`voucher_lines(account_id)`。
- `ledger_entries(account_id, entry_date, id)`、`ledger_entries(period_id, account_id)`。
- `audit_logs(entity_type, entity_id, created_at)`。

## 5. 核心會計規則（必須實作）

1. 一張傳票至少兩列有效分錄，總借方 = 總貸方且總額 > 0。
2. 每列不可同時有借方與貸方，也不可兩者都為零；金額不得為負。
3. 僅啟用、可過帳的葉節點科目可用於傳票。
4. 會計期間必須存在、與傳票日期一致且處於 Open。
5. 狀態機：`DRAFT → SUBMITTED → APPROVED → POSTED`；`SUBMITTED → REJECTED → DRAFT`。已過帳不可直接編輯或刪除。
6. 過帳須在單一 DB transaction 中完成：驗證狀態與平衡 → 建立 ledger entries → 更新 voucher 狀態 → 寫 audit log → commit；任何失敗 rollback。
7. 重複呼叫過帳 API 不得產生第二份總帳分錄；已過帳時回傳明確結果或衝突錯誤。
8. 沖銷以新的反向傳票處理，保留原傳票；沖銷傳票也須審核與過帳；避免重複沖銷。
9. 期末結帳：Phase 1 先支援關閉期間及跨期報表正確計算；真正收入費用結轉傳票列後續 Phase，需避免將累計損益重複列入權益。
10. 借方正常餘額：資產、費用；貸方正常餘額：負債、權益、收入。不得單純將負數視為錯誤。
11. 損益表按**期間發生額**計算；資產負債表按**截至日累計餘額**計算，並處理期初與未結轉損益。
12. 試算平衡只是借貸檢查，不能證明所有帳務都正確。

## 6. 主要頁面與 UX

- `/login` 登入。
- `/dashboard` 儀表板：本月收入、費用、損益、待審傳票、未平衡警示。
- `/accounts` 科目清單與新增/編輯。
- `/vouchers` 傳票列表；`/vouchers/new` 傳票輸入；`/vouchers/<id>` 詳細資料與狀態歷程。
- `/reports/cashbook`、`/reports/journal`、`/reports/daily`、`/reports/ledger`、`/reports/trial-balance`、`/reports/income-statement`、`/reports/balance-sheet`、`/reports/costs`、`/reports/expenses`、`/reports/financial-analysis`。
- `/admin/users`、`/admin/periods`、`/admin/settings`、`/admin/integrity`、`/admin/audit`。

介面要求：繁體中文、左側三大選單（登錄作業／報表作業／維護作業）、桌面表格、明確的狀態標籤、金額千分位、錯誤提示、無資料狀態、查詢條件保留。傳票編輯時即時計算借貸差額；**前端檢查不能取代後端驗證**。

## 7. API 規格（示例）

| Method | Endpoint | 功能 |
|---|---|---|
| GET/POST | `/api/v1/accounts` | 科目查詢／新增 |
| GET/PATCH | `/api/v1/accounts/{id}` | 科目明細／更新 |
| GET/POST | `/api/v1/vouchers` | 傳票查詢／建立 |
| GET/PATCH | `/api/v1/vouchers/{id}` | 傳票讀取／草稿修改 |
| POST | `/api/v1/vouchers/{id}/submit` | 送審 |
| POST | `/api/v1/vouchers/{id}/approve` | 核准 |
| POST | `/api/v1/vouchers/{id}/reject` | 駁回 |
| POST | `/api/v1/vouchers/{id}/post` | 原子過帳 |
| POST | `/api/v1/vouchers/{id}/reverse` | 建立沖銷傳票 |
| GET | `/api/v1/reports/trial-balance?as_of=YYYY-MM-DD` | 試算表 |
| GET | `/api/v1/reports/income-statement?from=...&to=...` | 損益表 |
| GET | `/api/v1/reports/balance-sheet?as_of=...` | 資產負債表 |
| GET | `/api/v1/reports/ledger?account_id=...&from=...&to=...` | 分類帳 |

回應示例：`{"data": {...}, "meta": {...}}`；錯誤：`{"error": {"code": "VOUCHER_UNBALANCED", "message": "借貸金額不平衡"}}`。提供 400/401/403/404/409 等適當 HTTP 狀態碼。對修改與過帳應考慮並行操作與重複請求防護。

## 8. DEMO 資料（必須可一鍵載入）

科目：
- 1001 銀行存款（Asset）
- 1501 生產設備（Asset）
- 3001 資本（Equity）
- 4001 銷貨收入（Revenue）
- 6001 水電費（Expense）

已過帳交易（同一開放會計期間）：

| 傳票 | 借方 | 貸方 | 金額 |
|---|---|---|---:|
| JV-001 | 銀行存款 | 資本 | 1,000,000 |
| JV-002 | 水電費 | 銀行存款 | 100,000 |
| JV-003 | 銀行存款 | 銷貨收入 | 300,000 |

預期結果（假設無其他交易、成本、稅金及期初餘額）：
- 銀行存款：1,200,000。
- 收入：300,000；費用：100,000；本期淨利：200,000。
- 資產：1,200,000；負債：0；權益（含本期未結轉損益）：1,200,000。
- 試算表借方餘額合計與貸方餘額合計均為 1,300,000。

額外建立「購買設備 500,000，以銀行支付」**獨立測試案例**，借生產設備、貸銀行存款；資產總額不因資產間轉換而改變，且不立即將 500,000 全數認列為費用。不要直接改變前述 DEMO 基準資料的預期數字。

## 9. 自動化測試與驗收

使用 pytest；至少包含：

- 科目新增/修改、重複代碼、不可過帳科目阻擋。
- 借貸不平、零金額、負數、同列雙邊金額、少於兩列均拒絕。
- 草稿 → 送審 → 核准 → 過帳成功；未核准不可過帳。
- 同一傳票重複過帳，ledger entries 數量不增加。
- 模擬 ledger insert 失敗時 rollback，傳票仍非 POSTED。
- 關閉期間禁止新增、修改、過帳。
- 已過帳傳票不可直接修改或刪除；沖銷可追溯。
- 非授權使用者不可審核、過帳、重置 DEMO 資料。
- 試算表借貸合計相等、損益表與資產負債表符合 DEMO 數字。
- 報表日期邊界、跨月、跨年、期初餘額及沖銷後結果正確。
- SQL 注入與 XSS 基本防護；CSRF 驗證；未登入 API 禁止存取。

完成時必須提供：`pytest` 結果、資料庫 migration 操作、DEMO 初始化指令、啟動指令、測試帳號建立方式（不要在正式環境硬編碼密碼）、API 文件、已知限制。

## 10. 分階段交付

### Phase 1 — 可用的 GL MVP（優先實作）
- Flask 專案骨架、資料庫 migration、登入與角色。
- 科目主檔、會計期間、傳票 CRUD/審核/過帳。
- 分類帳、試算表、損益表、資產負債表。
- DEMO seed、單元與整合測試。
- **驗收：三張 DEMO 傳票過帳後，四張報表數字全部正確。**

### Phase 2 — 完整傳統報表與維護
- 現金簿、日記簿、日計表、簡化營業成本表、費用分析表、財務分析表。
- CSV、列印、稽核日誌、完整性檢查、備份、DEMO 重置。
- **驗收：報表可篩選期間、科目且可追溯到傳票。**

### Phase 3 — 可擴充 ERP 整合
- 來源系統欄位 `source_type/source_ref`、外部來源傳票匯入 API。
- 冪等鍵、來源追蹤、錯誤佇列/重試策略（先設計再實作）。
- 研究 MES 領料、成品入庫、銷貨成本如何對應會計分錄；不直接在 GL 中臆造庫存成本。
- **驗收：外部同一業務事件重送不會重複入帳。**

## 11. 專案結構建議

```text
gl-accounting/
  app/
    __init__.py
    config.py
    extensions.py
    models/
    blueprints/
      auth/
      accounts/
      periods/
      vouchers/
      posting/
      reports/
      admin/
    services/
      accounting_service.py
      posting_service.py
      report_service.py
    templates/
    static/
  migrations/
  tests/
  scripts/
    seed_demo.py
  instance/
  .env.example
  requirements.txt
  README.md
  run.py
```

## 12. Codex 回報格式

每完成一個 Phase，請用繁體中文回報：

1. 完成的功能與實際操作路徑。
2. 修改/新增的檔案清單。
3. 資料庫 schema / migration 變更。
4. 執行指令、測試結果及實際輸出。
5. 已知問題與尚未實作的功能。
6. 下一 Phase 的具體工作項目。

**立即開始 Phase 1。不要跳過測試，不要以純靜態假畫面代替真正的會計運算。**
