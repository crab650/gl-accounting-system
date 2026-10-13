"""Prepare and, after user review, publish GL source explanations to Code Knowledge."""

import argparse
import ast
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = Path(os.environ.get("CODEKNOWLEDGE_SETTINGS_PATH", ROOT.parent / "AI Code Knowledge Agent" / "instance" / "local_settings.json"))
BASE_URL = os.environ.get("CODEKNOWLEDGE_API_BASE", "http://127.0.0.1:5000/api").rstrip("/")
REVIEW = ROOT / "docs" / "知識庫預覽.md"

PROJECT_NAME = "GL Accounting System"
CATEGORY_NAME = "總帳會計"
FEATURES = {
    "voucher": ("傳票驗證與過帳", "傳票分錄、草稿保存與原子過帳"),
    "reports": ("核心財務報表", "試算表、損益表與資產負債表的計算"),
}

SPECS = [
    {
        "symbol": "validate_lines", "feature": "voucher", "title": "validate_lines()：分錄與借貸平衡驗證",
        "technical": "先要求至少兩列，再逐列以 Decimal 轉換金額為整數分，檢查科目存在、啟用、可過帳且沒有子科目。每列借貸只能一側為正數；最後要求總借方等於總貸方且大於零。錯誤以 BusinessError 中斷。",
        "business": "防止不平衡、零金額或無效科目的傳票進入保存與過帳流程。",
        "tables": [("accounts", "查詢科目啟用、可過帳及是否有子科目")],
        "flow": "flowchart TD\nLines[輸入分錄] --> Count{至少兩列}\nCount --> Account[逐列檢查科目與金額]\nAccount --> Balance{借貸總額相等且大於零}\nBalance --> Result[回傳正規化分錄]",
    },
    {
        "symbol": "save_voucher", "feature": "voucher", "title": "save_voucher()：建立或修改傳票草稿",
        "technical": "若修改既有傳票，先限制狀態為 DRAFT。解析日期及期間、驗證分錄與編號唯一性後，寫入 vouchers 與 voucher_lines；修改時刪除舊分錄再建立新分錄。新增 SAVE 稽核紀錄，commit=True 時提交交易。",
        "business": "將通過後端會計規則的傳票保存為可送審草稿，並留下操作者紀錄。",
        "tables": [("vouchers", "保存傳票主檔、日期、期間與狀態"), ("voucher_lines", "保存逐列借貸分錄"), ("audit_logs", "記錄 SAVE 操作")],
        "flow": "flowchart TD\nInput[傳票資料] --> Period[檢查開放期間]\nPeriod --> Lines[驗證借貸分錄]\nLines --> Unique[檢查編號唯一]\nUnique --> Save[寫入主檔與分錄]\nSave --> Audit[寫稽核紀錄]\nAudit --> Commit[提交交易]",
    },
    {
        "symbol": "post_voucher", "feature": "voucher", "title": "post_voucher()：原子過帳與失敗回滾",
        "technical": "只接受 APPROVED 傳票；重新檢查期間與分錄。對每列 VoucherLine 建立一筆 LedgerEntry，接著將傳票設為 POSTED、記錄 UTC 過帳時間與 POST 稽核紀錄，最後在同一 DB session 提交。任何例外都 rollback 並重新拋出。ledger_entries.voucher_line_id 的唯一約束提供重複寫入防護。",
        "business": "核准後才讓分錄進入正式總帳；過帳失敗不留下部分入帳結果。",
        "tables": [("vouchers", "檢查並更新過帳狀態"), ("voucher_lines", "取得待過帳分錄"), ("ledger_entries", "建立正式總帳分錄；voucher_line_id 唯一"), ("audit_logs", "記錄 POST 操作")],
        "flow": "flowchart TD\nApproved[已核准傳票] --> Validate[重驗期間與借貸]\nValidate --> Ledger[逐列新增總帳分錄]\nLedger --> Status[更新為 POSTED]\nStatus --> Audit[寫稽核紀錄]\nAudit --> Commit[Commit]\nLedger -->|失敗| Rollback[Rollback]",
    },
    {
        "symbol": "balances", "feature": "reports", "title": "balances()：截至日科目餘額來源",
        "technical": "以 accounts 左連接 ledger_entries，條件限定 entry_date 不晚於截至日；依科目彙總借方與貸方整數分，將差額 debit-credit 作為 net。外連接讓沒有分錄的科目仍出現在中間結果。",
        "business": "提供試算表及資產負債表一致的截至日餘額基礎，報表只取正式總帳資料。",
        "tables": [("accounts", "列出科目與類型"), ("ledger_entries", "累計截至日已過帳借貸發生額")],
        "flow": "flowchart TD\nDate[截至日] --> Join[科目左連接總帳]\nJoin --> Sum[依科目彙總借貸]\nSum --> Net[計算借減貸淨額]",
    },
    {
        "symbol": "trial_balance", "feature": "reports", "title": "trial_balance()：試算表借貸餘額",
        "technical": "呼叫 balances(as_of) 取得各科目借減貸淨額，排除零餘額；正數列入借方餘額，負數取絕對值列入貸方餘額，最後分別加總。",
        "business": "在指定截至日檢查各科目借貸餘額總和是否相等；相等只代表借貸平衡，不保證所有帳務分類正確。",
        "tables": [],
        "flow": "flowchart TD\nBalances[balances 截至日淨額] --> Split{淨額方向}\nSplit --> Debit[正數列借方]\nSplit --> Credit[負數列貸方]\nDebit --> Total[分別加總]\nCredit --> Total",
    },
    {
        "symbol": "income_statement", "feature": "reports", "title": "income_statement()：期間損益計算",
        "technical": "先檢查起日不晚於迄日。查詢日期範圍內的 ledger_entries，只取 REVENUE 與 EXPENSE 科目並按科目彙總；收入以貸減借、費用以借減貸計算，最後以收入減費用得到本期損益。",
        "business": "顯示指定期間的收入、費用與損益，避免把期外分錄列入本期。",
        "tables": [("accounts", "篩選收入與費用類型科目"), ("ledger_entries", "查詢期間內已過帳分錄")],
        "flow": "flowchart TD\nDates[起迄日期] --> Entries[篩選收入與費用總帳]\nEntries --> Aggregate[按科目彙總]\nAggregate --> Profit[收入減費用]",
    },
    {
        "symbol": "balance_sheet", "feature": "reports", "title": "balance_sheet()：截至日資產負債與未結轉損益",
        "technical": "呼叫 balances(as_of) 取得累計淨額，依科目類型調整正常餘額方向。資產、負債、權益列成明細；收入減費用得到未結轉損益，再加到權益總額。",
        "business": "呈現截至日資產、負債及包含本期未結轉損益的權益，支援尚未製作收入費用結轉傳票的第一版流程。",
        "tables": [],
        "flow": "flowchart TD\nBalances[balances 截至日淨額] --> Types[依科目類型調整方向]\nTypes --> Assets[資產]\nTypes --> Liabilities[負債]\nTypes --> Equity[權益]\nTypes --> Profit[收入減費用]\nProfit --> Equity",
    },
]

RELATIONS = [
    ("save_voucher", "validate_lines"),
    ("post_voucher", "validate_lines"),
    ("trial_balance", "balances"),
    ("balance_sheet", "balances"),
]


def api(method, path, payload=None):
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    token = settings["api_token"]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(BASE_URL + path, data=body, method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
            if not result.get("success"):
                raise RuntimeError(f"{method} {path}: {result.get('error')}")
            return result["data"]
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path}: HTTP {error.code}: {detail[:500]}") from error


def find_or_create(items, name, path, payload):
    found = next((item for item in items if item["name"] == name), None)
    return found if found else api("POST", path, payload)


def ensure_features():
    context = api("GET", "/agent/context")
    project = find_or_create(context["projects"], PROJECT_NAME, "/projects",
        {"name": PROJECT_NAME, "description": "財務會計總帳系統原始碼與會計運算知識"})
    detail = api("GET", f"/agent/context/{project['id']}")
    category = find_or_create(detail["categories"], CATEGORY_NAME, "/categories",
        {"project_id": project["id"], "name": CATEGORY_NAME, "description": "總帳傳票與財務報表"})
    detail = api("GET", f"/agent/context/{project['id']}")
    category = next(item for item in detail["categories"] if item["name"] == CATEGORY_NAME)
    result = {}
    for key, (name, description) in FEATURES.items():
        result[key] = find_or_create(category.get("features", []), name, "/features",
            {"category_id": category["id"], "name": name, "description": description})["id"]
    return project["id"], result


def source_function(name):
    path = ROOT / "app" / "services.py"
    source = path.read_text(encoding="utf-8")
    node = next(item for item in ast.parse(source).body if isinstance(item, ast.FunctionDef) and item.name == name)
    return node.lineno, node.end_lineno, "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])


def payload_for(spec, feature_id):
    start, end, code = source_function(spec["symbol"])
    return {"feature_id": feature_id, "title": spec["title"], "file_path": "app/services.py",
        "symbol_name": spec["symbol"], "symbol_type": "function", "start_line": start, "end_line": end,
        "language": "python", "source_code": code, "technical_explanation": spec["technical"],
        "business_explanation": spec["business"], "tables": [
            {"table_name": name, "usage_note": note} for name, note in spec["tables"]],
        "flow_source": spec["flow"], "analysis_status": "reviewed"}


def existing_analysis(feature_id, payload):
    items = api("GET", f"/analyses?feature_id={feature_id}")
    for item in items:
        if item.get("file_path") == payload["file_path"] and item.get("symbol_name") == payload["symbol_name"]:
            return api("GET", f"/analyses/{item['id']}")
    return None


def prepare():
    project_id, feature_ids = ensure_features()
    lines = ["# GL Accounting System 知識庫預覽", "", f"Project ID：{project_id}",
        "", "下列程式碼從目前 Repository 原檔擷取。各段均沒有手寫 SQL，因此不另建 SQL Snippet。", ""]
    staged = []
    for spec in SPECS:
        payload = payload_for(spec, feature_ids[spec["feature"]])
        existing = existing_analysis(payload["feature_id"], payload)
        preview = api("POST", "/analyses/preview", payload)
        staged.append((spec, payload, existing))
        lines += [f"## {payload['title']}", "", f"來源：`{payload['file_path']}:{payload['start_line']}` 至第 {payload['end_line']} 行",
                  f"Feature ID：{payload['feature_id']}；{'將更新 ID '+str(existing['id']) if existing else '將新增'}", "",
                  "### 原始碼", "", "```python", payload["source_code"], "```", "", "### 技術說明", "",
                  payload["technical_explanation"], "", "### 業務說明", "", payload["business_explanation"], "",
                  "### 資料表引用", ""]
        lines += [f"- `{row['table_name']}`：{row['usage_note']}" for row in payload["tables"]] or ["- 此函式透過其他函式取得資料；本段沒有直接 ORM 資料表引用。"]
        lines += ["", "### 流程圖", "", "```mermaid", payload["flow_source"], "```", ""]
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text("\n".join(lines), encoding="utf-8")
    print(f"Prepared {len(staged)} previews")
    return staged


def publish():
    staged = prepare()
    saved = {}
    for spec, payload, existing in staged:
        confirmed = {**payload, "confirmed": True}
        if existing:
            result = api("PATCH", f"/analyses/{existing['id']}", confirmed)
        else:
            result = api("POST", "/analyses", confirmed)
        saved[spec["symbol"]] = result["id"]
        print(f"{spec['symbol']}: analysis {result['id']}")
    for caller, callee in RELATIONS:
        analysis_id, related_id = saved[caller], saved[callee]
        current = api("GET", f"/analyses/{analysis_id}")
        relations = current.get("related_analyses", [])
        if not any(item.get("related_analysis_id", item.get("id")) == related_id and item.get("relation_type") == "calls" for item in relations):
            api("POST", f"/analyses/{analysis_id}/relations",
                {"related_analysis_id": related_id, "relation_type": "calls", "confirmed": True})
    for symbol, analysis_id in saved.items():
        current = api("GET", f"/analyses/{analysis_id}")
        if current.get("symbol_name") != symbol:
            raise RuntimeError(f"Verification failed for {symbol}")
    print(f"Verified {len(saved)} analyses")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "publish"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        publish()
