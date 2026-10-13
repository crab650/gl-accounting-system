# PythonAnywhere 掛載式 Flask 專案設計規範

## 1. 目的

本文件定義後續 Flask 專案的共通設計方式。專案應能部署到 PythonAnywhere，並可掛載於網站的子路徑，而不限定只能使用網域根目錄。

例如同一個網站可掛載多個獨立系統：

```text
https://example.pythonanywhere.com/energy/
https://example.pythonanywhere.com/footwear/
https://example.pythonanywhere.com/inventory/
```

每個系統應保持獨立程式碼、設定、資料庫與 Session，新增或更新其中一個系統時，不應影響其他系統。

## 2. 核心原則

1. 程式內不得寫死網站網域或根路徑。
2. 所有站內網址由 Flask `url_for()` 產生。
3. 應使用 application factory 建立 Flask application。
4. 開發環境與正式環境設定必須分離。
5. 密鑰、密碼和連線資訊不得寫死在原始碼中。
6. 程式檔與持久化資料應分開保存，更新程式時不得覆蓋正式資料。
7. 每個掛載系統使用不同的 Session cookie 名稱。
8. WSGI 是正式環境唯一入口；`app.run()` 僅供本機開發。

## 3. 建議目錄結構

```text
footwear/
├─ footwear_app/
│  ├─ __init__.py          # create_app()
│  ├─ config.py
│  ├─ db.py
│  ├─ auth/
│  ├─ admin/
│  ├─ main/
│  ├─ templates/
│  └─ static/
├─ instance/               # 本機資料；不提交正式 DB
├─ migrations/             # 若採用資料庫 migration
├─ tests/
├─ requirements.txt
├─ wsgi.py                 # 單一專案 WSGI 入口
├─ .env.example
└─ README.md
```

正式資料建議放在程式發布目錄之外，例如：

```text
/home/account/apps/footwear/current/       # 目前程式版本
/home/account/apps/footwear/shared/        # 持久化資料
└─ data/app.db
```

如此替換 `current` 內的程式時，`shared/data/app.db` 不會被覆蓋。

## 4. Flask application factory

不要在模組匯入時完成所有初始化。由 `create_app()` 接收設定並建立 application：

```python
import os
from pathlib import Path

from flask import Flask


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    data_dir = Path(os.environ.get("FOOTWEAR_DATA_DIR", app.instance_path))
    data_dir.mkdir(parents=True, exist_ok=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ["FOOTWEAR_SECRET_KEY"],
        DATABASE=str(data_dir / "app.db"),
        SESSION_COOKIE_NAME="footwear_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if config:
        app.config.update(config)

    from .main import bp as main_bp
    app.register_blueprint(main_bp)

    return app
```

正式環境如果全站使用 HTTPS，可再設定：

```python
SESSION_COOKIE_SECURE = True
```

不同專案必須使用不同的環境變數前綴與 `SESSION_COOKIE_NAME`，避免互相覆蓋 Session。

## 5. 子路徑相容設計

### 5.1 必須使用 `url_for()`

模板中的連結、表單和靜態檔案：

```html
<a href="{{ url_for('main.index') }}">首頁</a>
<form method="post" action="{{ url_for('auth.logout') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/app.css') }}">
```

後端重新導向：

```python
return redirect(url_for("main.index"))
```

前端 JavaScript 若需要 API 網址，應由模板注入：

```html
<script>
    const saveUrl = {{ url_for('main.save') | tojson }};
</script>
```

不可寫成以下形式：

```text
href="/login"
fetch("/api/save")
window.location = "/admin"
```

因為前導 `/` 會跳回整個網域根目錄，遺失 `/footwear` 掛載前綴。

### 5.2 Redirect 的 next 參數

接收 `next` 網址時只允許站內相對網址，避免 open redirect：

```python
next_url = request.form.get("next", "")
if not next_url.startswith("/") or next_url.startswith("//"):
    next_url = url_for("main.index")
return redirect(next_url)
```

模板可保留目前包含掛載前綴的網址：

```html
<input type="hidden" name="next"
       value="{{ request.script_root }}{{ request.full_path }}">
```

## 6. WSGI 掛載方式

### 6.1 專案自己的 WSGI 入口

專案根目錄的 `wsgi.py`：

```python
from footwear_app import create_app

application = create_app()
```

### 6.2 在 PythonAnywhere 掛載多個系統

PythonAnywhere Web 設定頁所指定的 WSGI configuration file，可使用 Werkzeug 的 `DispatcherMiddleware`：

```python
import sys

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response

sys.path.insert(0, "/home/account/apps/footwear/current")
sys.path.insert(0, "/home/account/apps/energy/current")

from footwear_app import create_app as create_footwear_app
from energy_app import create_app as create_energy_app


def not_found(environ, start_response):
    response = Response("Not Found", status=404)
    return response(environ, start_response)


application = DispatcherMiddleware(
    not_found,
    {
        "/footwear": create_footwear_app(),
        "/energy": create_energy_app(),
    },
)
```

`DispatcherMiddleware` 會把掛載前綴放入 WSGI 的 `SCRIPT_NAME`。Flask 的 `url_for()` 會據此產生帶有 `/footwear` 或 `/energy` 的網址。

掛載名稱建議只使用小寫英文字母、數字和連字號，且結尾不要加 `/`。

## 7. SQLite 設計

SQLite 適合 DEMO、小型內部系統及寫入量不高的情境。使用時應遵守：

- 資料庫使用絕對路徑或由環境變數決定。
- 不把正式 `.db` 提交到 Git。
- 每個 request 建立連線，request 結束後關閉。
- 啟用 foreign key；視需求設定 busy timeout 和 WAL。
- Schema 初始化和 migration 不應在每個 request 重複執行。
- 部署新版前先備份資料庫。
- 備份時使用 SQLite backup API 或安全的一致性備份方式，不要任意複製正在寫入中的 DB/WAL 檔案。

連線範例：

```python
import sqlite3

from flask import current_app, g


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db = sqlite3.connect(
            current_app.config["DATABASE"],
            timeout=10,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        g.db = db
    return g.db
```

若未來有大量同時寫入、背景工作或多台 application server，應改用 MySQL 或 PostgreSQL。

## 8. 安全基準

- 密碼使用 Werkzeug 的 `generate_password_hash()` 與 `check_password_hash()`。
- `SECRET_KEY` 使用環境變數，正式環境不得使用預設值。
- 所有會改變資料的表單及 API 應有 CSRF 保護。
- SQL 一律使用參數化查詢。
- 登入後應依後端權限檢查路由，不能只隱藏前端按鈕。
- 上傳檔案需限制副檔名、內容、大小與儲存位置。
- 正式環境關閉 Flask debug mode。
- 記錄必要的操作與錯誤，但不得將密碼或 Session 寫入 log。

## 9. requirements.txt

依實際使用套件鎖定版本範圍，例如：

```text
Flask>=3.1,<4
Werkzeug>=3.1,<4
openpyxl>=3.1,<4
```

若新增 CSRF、ORM 或 migration，再加入相對應套件。PythonAnywhere virtualenv 的 Python 版本必須與建立環境時選擇的版本一致。

## 10. 部署流程

1. 將程式上傳或由 Git 取得到專案目錄。
2. 建立 PythonAnywhere virtualenv 並安裝 `requirements.txt`。
3. 建立專案專用的持久化資料目錄。
4. 設定 `SECRET_KEY`、資料庫路徑及其他正式環境設定。
5. 第一次部署時執行明確的資料庫初始化或 migration 指令。
6. 在 PythonAnywhere WSGI configuration file 加入掛載設定。
7. 在 Web 頁面設定正確的 virtualenv。
8. Reload web app。
9. 測試首頁、登入、表單、匯出、靜態檔案與重新導向。
10. 確認所有網址均保留掛載前綴。

## 11. 發布與更新策略

建議將程式版本與共用資料分離：

```text
releases/2026-08-06_01/
releases/2026-08-12_01/
current -> releases/2026-08-12_01/
shared/data/app.db
```

標準更新順序：

1. 備份資料庫。
2. 上傳新版本至新的 release 目錄。
3. 安裝或更新依賴。
4. 執行 migration。
5. 將 `current` 切換到新版本。
6. Reload PythonAnywhere web app。
7. 執行 smoke test。

PythonAnywhere 或使用環境若不適合 symbolic link，也可維持固定程式目錄，但仍必須把 DB、上傳檔案和密鑰放在程式目錄之外。

## 12. 驗收檢查表

- [ ] 系統可在本機 `/` 正常執行。
- [ ] 系統掛載在 `/footwear` 後仍可正常執行。
- [ ] 頁面連結、表單 action、AJAX 和靜態檔案均保留掛載前綴。
- [ ] 登入與登出後的 redirect 正確。
- [ ] 多個掛載系統的 Session 不會互相覆蓋。
- [ ] Reload 後資料仍存在。
- [ ] 更新程式不會覆蓋資料庫或上傳檔案。
- [ ] 正式環境未啟用 debug mode。
- [ ] 原始碼內沒有正式密鑰或明碼密碼。
- [ ] 資料庫可備份並完成還原測試。

## 13. Energy DEMO 的沿用原則

`ref/Energy/prototype` 可作為功能流程、表格操作、權限概念及畫面配置的參考。其模板大多透過 `url_for()` 產生網址，已具備部分子路徑相容性。

新專案不直接沿用下列 DEMO 作法：

- 原始碼內固定的 `SECRET_KEY`。
- 明碼儲存密碼。
- 每個 request 都執行資料庫建表與 seed。
- 資料庫固定放在程式碼內的 `instance/app.db`。
- 只提供 `app.run(debug=True)` 而沒有正式 WSGI 與部署設定。

後續專案應以本文件為部署與架構基準，再依實際功能擴充。
