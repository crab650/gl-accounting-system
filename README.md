# GL Accounting Demo

依照 [財務會計總帳系統規格](財務會計總帳系統_Codex開發規格.md) 與 [PythonAnywhere 部署規範](PythonAnywhere掛載式Flask專案設計規範.md) 建立的 Phase 1 總帳系統。這是單公司、單帳簿、兩位小數的示範系統。所有報表只讀取 `ledger_entries`；傳票分錄不會直接計入報表。

> 📖 **完整圖解操作手冊**：請參閱採用 [HELLO.webp](docs/HELLO.webp) 極簡視覺化排版之 [系統操作流程指引](docs/系統操作流程.md)，包含步驟編號、畫面截圖與完整業務流程。

---

## 📸 核心功能操作介紹 (Operation Highlights)

本系統具備標準會計內部控制流程，以下列出核心功能的操作步驟與畫面截圖：

### 1. 營運儀表板 (Dashboard)
系統啟動後首頁即時彙整當月收入、費用、本期損益以及待審核傳票數量，便於管理階層與會計主管掌握即時財務狀態。

![營運儀表板](docs/images/01_dashboard.png)

### 2. 會計科目維護 (Chart of Accounts)
支援五大類會計要素（資產、負債、權益、收入、費用）的階層式管理。具備不可循環參照之階層防呆，且已使用的科目禁止任意竄改科目類型。

![會計科目維護](docs/images/02_accounts.png)

### 3. 傳票錄入與借貸即時平衡防呆 (Voucher Entry)
落實複式簿記原則，畫面提供前端即時計算借貸差額功能。唯有借方與貸方總額相等（差額為 0.00）時，才允許儲存傳票草稿。

![傳票錄入](docs/images/03_new_voucher.png)

### 4. 傳票審核、過帳與反向沖銷 (Approval & Posting Workflow)
嚴格落實內部控制與不可竄改性（Immutability）：
- 草稿需經送審 (Submit) 與主管核准 (Approve) 才能進行過帳 (Post)。
- 過帳後自動在單一資料庫交易中寫入不可竄改的總帳分錄 (`ledger_entries`)。
- 已過帳傳票不得直接修改或刪除，需透過「建立沖銷傳票」生成借貸相反的紅字沖銷傳票，留下完整稽核軌跡。

![傳票明細與過帳沖銷](docs/images/04_voucher_detail.png)

### 5. 即時產出四大財務報表 (Financial Reports)
所有財務報表（試算表、資產負債表、損益表、明細分類帳）直接從已過帳總帳資料表統計產出，確保數據真實一致。內建列印專用排版樣式。

![試算表](docs/images/05_trial_balance.png)

---

## 開發計畫

1. **Phase 1（目前）**：登入與角色、科目、期間、傳票狀態與過帳、分類帳、試算表、損益表、資產負債表、DEMO seed、測試。
2. **Phase 2**：其他傳統報表、CSV、列印改善、完整性檢查、備份與還原、DEMO 重置。
3. **Phase 3**：外部來源匯入、冪等鍵、ERP 追蹤。

主要檔案架構：

```text
app/__init__.py       application factory、設定、CSRF、SQLite pragma
app/models.py         資料模型
app/services.py       會計驗證、狀態機、過帳、四張報表
app/routes.py         HTML 頁面與 JSON API
app/commands.py       migration、使用者、DEMO 資料命令
migrations/           Alembic 初始 revision
app/templates/        繁體中文頁面
app/static/           CSS、傳票借貸差額提示
tests/                pytest 驗收
wsgi.py               正式 WSGI 入口
run.py                本機啟動入口
docs/系統操作流程.md   視覺化操作指南（含畫面截圖）
```

## 本機啟動

Windows 可直接雙擊 [啟動財務系統.bat](啟動財務系統.bat)。它會檢查 Python 3.11 以上與依賴、執行資料庫 migration、建立本機操作身分，並在服務可連線後自動開啟 `http://127.0.0.1:8765/`，不需輸入帳號密碼。若 8765 已被占用，會改用 8766，實際網址以命令視窗顯示為準。**使用期間請保持 BAT 的命令視窗開啟**；關閉視窗或按 Ctrl+C 即停止服務。此免登入模式只由 BAT 啟用，網站綁定 `127.0.0.1`；一般 WSGI 部署仍使用登入。預設資料與本機密鑰保存在 `instance/`，不提交到 Git。也可預先設定 `GL_DATA_DIR` 和 `GL_SECRET_KEY` 覆蓋本機預設值。

PowerShell 手動啟動範例：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:GL_SECRET_KEY = "請換成長且隨機的密鑰"
$env:GL_DATA_DIR = "D:\gl-data"
python -m flask --app wsgi:application init-db
python -m flask --app wsgi:application create-user --username admin --role ADMIN
python -m flask --app wsgi:application seed-demo --actor admin --year 2026
python run.py
```

`python run.py` 也使用本機免登入模式與 8765（必要時使用 8766）。一般 WSGI 部署可用 `create-user` 建立登入帳號，密碼由命令提示輸入。`init-db` 執行 Alembic `upgrade head`，初始 revision 為 `b12ef3ec2083`；之後可用 `python -m flask --app wsgi:application db upgrade` 更新 schema。不可在每個 request 執行初始化。

執行測試：

```powershell
python -m pytest -q
```

## 操作流程簡述

1. 管理員建立會計期間及帳號；會計人員維護科目。
2. 會計人員新增平衡的傳票、送審。
3. 核准者核准；會計人員過帳。ADMIN 可執行全部步驟。
4. 過帳會在同一資料庫交易內新增總帳分錄、更新狀態、寫入稽核日誌。已過帳傳票不可直接修改，須建立反向沖銷傳票並再次送審、核准與過帳。
5. 查閱分類帳、試算表、損益表與資產負債表。金額以整數分儲存，畫面以元顯示。

`seed-demo` 建立 `JV-001` 至 `JV-003`，預期銀行存款 1,200,000、收入 300,000、費用 100,000、淨利 200,000、試算借貸各 1,300,000。設備購買是獨立測試，不會改動 seed 數字。

## 科目類型

新增科目時可以選擇資產、負債、權益、收入或費用。各類型的意思、例子、正常餘額方向與報表位置見 [科目類型說明](docs/科目類型說明.md)，系統「會計科目」頁也有完整表格。API 的 `type` 欄位仍使用 `ASSET`、`LIABILITY`、`EQUITY`、`REVENUE`、`EXPENSE`。

程式碼知識庫頁面的 `symbol_type` 另見 [知識庫類型說明](docs/知識庫類型說明.md)。本專案已保存的七篇分析皆為 `function`。

## API v1

所有 API 使用登入 Session。變更資料的請求須在 `X-CSRF-Token` header 提供登入頁或頁面表單中的 CSRF token。成功回應採 `{ "data": ... }`，錯誤採 `{ "error": { "code": ..., "message": ... } }`。日期格式為 `YYYY-MM-DD`，輸入金額為最多兩位小數字串；輸出金額欄位使用整數分。

| 方法 | 路徑 | 用途 |
|---|---|---|
| GET/POST | `/api/v1/accounts` | 清單／新增科目 |
| GET/PATCH | `/api/v1/accounts/{id}` | 讀取／更新科目 |
| GET/POST | `/api/v1/vouchers` | 清單／新增傳票 |
| GET/PATCH | `/api/v1/vouchers/{id}` | 讀取／修改草稿 |
| POST | `/api/v1/vouchers/{id}/submit` | 送審 |
| POST | `/api/v1/vouchers/{id}/approve` | 核准 |
| POST | `/api/v1/vouchers/{id}/reject` | 駁回 |
| POST | `/api/v1/vouchers/{id}/redraft` | 駁回後退回草稿 |
| POST | `/api/v1/vouchers/{id}/post` | 過帳 |
| POST | `/api/v1/vouchers/{id}/reverse` | 建立沖銷草稿 |
| GET | `/api/v1/reports/ledger?account_id=1&from=2026-01-01&to=2026-12-31` | 分類帳 |
| GET | `/api/v1/reports/trial-balance?as_of=2026-12-31` | 試算表 |
| GET | `/api/v1/reports/income-statement?from=2026-01-01&to=2026-12-31` | 損益表 |
| GET | `/api/v1/reports/balance-sheet?as_of=2026-12-31` | 資產負債表 |

傳票建立範例：

```json
{"voucher_no":"JV-100","voucher_date":"2026-01-15","period_id":1,"description":"資本投入","lines":[{"account_id":1,"debit":"1000.00","credit":"0"},{"account_id":2,"debit":"0","credit":"1000.00"}]}
```

## PythonAnywhere 子路徑掛載

設定 `GL_SECRET_KEY`、`GL_DATA_DIR` 為專案專用環境變數。將 `GL_DATA_DIR` 設在發佈目錄以外的持久化位置，例如 `/home/account/apps/gl/shared/data`。HTTPS 環境設定 `GL_SESSION_SECURE=1`。每個系統使用自己的 Session cookie 名稱。PythonAnywhere WSGI 設定可使用：

```python
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response
from app import create_app

application = DispatcherMiddleware(Response("Not Found", status=404), {
    "/gl": create_app(),
})
```

專案路徑需先加入 `sys.path`。所有模板連結、表單、靜態檔案使用 `url_for()`，可保留 `/gl` 前綴。部署前備份資料庫，執行 `init-db` 或後續 migration，再 reload WSGI；不要把正式 `.db` 或密鑰提交至版本庫。

---

## 🌐 English Overview

### Project Introduction
**GL Accounting System** is a robust, lightweight, and audit-compliant General Ledger Accounting application engineered with **Python (Flask)**, **SQLAlchemy**, and **Alembic**. It is developed specifically to implement strict double-entry bookkeeping standards with full immutability and complete internal control workflows.

### Core Architectural Highlights
1. **Single Source of Truth (`ledger_entries`)**:
   Financial reports (Balance Sheet, Income Statement, Trial Balance, General Ledger) exclusively aggregate entries from the posted `ledger_entries` table. Raw draft voucher lines are never directly aggregated into financial statements.
2. **Immutability & Complete Audit Trail**:
   Once a journal voucher is posted, it is permanently locked. Modifying or physically deleting posted entries is strictly prohibited. Accounting adjustments must be recorded via reverse offsetting vouchers (`reverse_voucher`), preserving a complete audit trail.
3. **Integer Cent Precision**:
   Monetary values are stored in the database as integer cents (e.g., `$1,000.00` is stored as `100000`). This completely avoids IEEE 754 floating-point inaccuracies during arithmetic operations.
4. **Finite State Machine Lifecycle**:
   Voucher state transitions follow strict governance: `DRAFT` ➔ `SUBMITTED` ➔ `APPROVED` ➔ `POSTED`. Vouchers rejected by approvers can be adjusted and re-drafted.
5. **Role-Based Access Control (RBAC)**:
   Clear role separation between `ADMIN`, `ACCOUNTANT`, `APPROVER`, and `VIEWER`.

### Quick Start (English)

#### Run on Windows
Double-click `啟動財務系統.bat` to automatically set up dependencies, run database migrations, initialize a local operator session, and launch the service at `http://127.0.0.1:8765/`.

#### Manual Setup via PowerShell
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m flask --app wsgi:application init-db
python -m flask --app wsgi:application create-user --username admin --role ADMIN
python -m flask --app wsgi:application seed-demo --actor admin --year 2026
python run.py
```
Open your browser and navigate to `http://127.0.0.1:8765/`.

---

## 已知限制

- 初版採 SQLite，適合低寫入量；高併發應評估 PostgreSQL。
- 目前只有初始 Alembic revision；後續 schema 變更需產出新 revision 並先備份資料庫。
- CSV 匯出、其他六張報表、備份還原、期間結轉、完整性檢查與外部 ERP 匯入屬後續階段。
- 尚無登入失敗次數限制；正式公開部署前需加入限制與監控。
- Bootstrap 5 使用 CDN 並有本機 CSS 作為離線備援；正式部署仍需在 PythonAnywhere 驗證依賴及子路徑設定。
