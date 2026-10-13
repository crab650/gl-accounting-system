from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import func, select
from . import db
from .models import Account, AuditLog, FiscalPeriod, LedgerEntry, Voucher, VoucherLine


class BusinessError(ValueError):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def money_minor(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise BusinessError("INVALID_AMOUNT", "金額格式錯誤")
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise BusinessError("INVALID_AMOUNT", "金額須為非負數且最多兩位小數")
    return int(amount * 100)


def money_text(minor):
    return f"{Decimal(minor) / 100:,.2f}"


def log(actor_id, action, entity_type, entity_id, before=None, after=None):
    db.session.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type,
                            entity_id=entity_id, before_json=before, after_json=after))


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise BusinessError("INVALID_DATE", "日期須為 YYYY-MM-DD")


def open_period(period_id, voucher_date):
    period = db.session.get(FiscalPeriod, period_id)
    if not period or period.status != "OPEN" or not period.start_date <= voucher_date <= period.end_date:
        raise BusinessError("PERIOD_CLOSED", "傳票日期須屬於開放的會計期間")
    return period


def validate_lines(lines):
    if len(lines) < 2:
        raise BusinessError("TOO_FEW_LINES", "傳票至少需要兩列分錄")
    debit = credit = 0
    normalized = []
    for row in lines:
        try:
            account_id = int(row["account_id"])
            account = db.session.get(Account, account_id)
            d, c = money_minor(row.get("debit", "0")), money_minor(row.get("credit", "0"))
        except (KeyError, TypeError, ValueError):
            raise BusinessError("INVALID_LINE", "分錄科目或金額不完整")
        if not account or not account.active or not account.postable or db.session.scalar(
            select(func.count()).select_from(Account).where(Account.parent_id == account_id)
        ):
            raise BusinessError("INVALID_ACCOUNT", "僅啟用的可過帳葉節點科目可用於傳票")
        if (d > 0) == (c > 0):
            raise BusinessError("INVALID_LINE", "每列只能在借方或貸方填入正數")
        debit += d
        credit += c
        normalized.append((account_id, str(row.get("description", "")), d, c))
    if debit != credit or debit == 0:
        raise BusinessError("VOUCHER_UNBALANCED", "借貸金額不平衡")
    return normalized


def save_voucher(data, actor_id, voucher=None, commit=True):
    if voucher and voucher.status != "DRAFT":
        raise BusinessError("INVALID_STATUS", "只能修改草稿傳票", 409)
    voucher_date = parse_date(data.get("voucher_date"))
    try:
        period_id = int(data.get("period_id"))
    except (TypeError, ValueError):
        raise BusinessError("INVALID_PERIOD", "請選擇會計期間")
    open_period(period_id, voucher_date)
    lines = validate_lines(data.get("lines", []))
    number = str(data.get("voucher_no", "")).strip()
    if not number or not str(data.get("description", "")).strip():
        raise BusinessError("REQUIRED_FIELD", "傳票編號及摘要不可空白")
    existing = db.session.scalar(select(Voucher).where(Voucher.voucher_no == number))
    if existing and (not voucher or existing.id != voucher.id):
        raise BusinessError("DUPLICATE_VOUCHER", "傳票編號已存在", 409)
    if voucher is None:
        voucher = Voucher(created_by=actor_id)
        db.session.add(voucher)
    voucher.voucher_no = number
    voucher.voucher_date = voucher_date
    voucher.period_id = period_id
    voucher.description = str(data["description"]).strip()
    if voucher.id:
        for old_line in list(voucher.lines):
            db.session.delete(old_line)
        db.session.flush()
    voucher.lines.clear()
    for i, (account_id, description, debit, credit) in enumerate(lines, 1):
        voucher.lines.append(VoucherLine(line_no=i, account_id=account_id,
                                         description=description, debit_minor=debit, credit_minor=credit))
    db.session.flush()
    log(actor_id, "SAVE", "voucher", voucher.id, after={"status": voucher.status})
    if commit:
        db.session.commit()
    return voucher


def transition(voucher, action, actor_id):
    states = {"submit": ("DRAFT", "SUBMITTED"), "approve": ("SUBMITTED", "APPROVED"),
              "reject": ("SUBMITTED", "REJECTED"), "redraft": ("REJECTED", "DRAFT")}
    if action not in states:
        raise BusinessError("INVALID_ACTION", "不支援的操作")
    old, new = states[action]
    if voucher.status != old:
        raise BusinessError("INVALID_STATUS", "傳票目前狀態不允許此操作", 409)
    open_period(voucher.period_id, voucher.voucher_date)
    validate_lines([{"account_id": line.account_id, "debit": Decimal(line.debit_minor) / 100,
                     "credit": Decimal(line.credit_minor) / 100} for line in voucher.lines])
    voucher.status = new
    if action == "approve":
        voucher.approved_by = actor_id
        voucher.approved_at = datetime.now(timezone.utc)
    log(actor_id, action.upper(), "voucher", voucher.id, {"status": old}, {"status": new})
    db.session.commit()
    return voucher


def post_voucher(voucher, actor_id):
    if voucher.status != "APPROVED":
        raise BusinessError("INVALID_STATUS", "只有已核准傳票可過帳", 409)
    open_period(voucher.period_id, voucher.voucher_date)
    validate_lines([{"account_id": line.account_id, "debit": Decimal(line.debit_minor) / 100,
                     "credit": Decimal(line.credit_minor) / 100} for line in voucher.lines])
    try:
        for line in voucher.lines:
            db.session.add(LedgerEntry(voucher_line_id=line.id, voucher_id=voucher.id,
                account_id=line.account_id, entry_date=voucher.voucher_date, period_id=voucher.period_id,
                debit_minor=line.debit_minor, credit_minor=line.credit_minor))
        voucher.status = "POSTED"
        voucher.posted_at = datetime.now(timezone.utc)
        log(actor_id, "POST", "voucher", voucher.id, {"status": "APPROVED"}, {"status": "POSTED"})
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return voucher


def reverse_voucher(voucher, actor_id, number):
    if voucher.status != "POSTED":
        raise BusinessError("INVALID_STATUS", "只能沖銷已過帳傳票", 409)
    if db.session.scalar(select(Voucher).where(Voucher.reversed_voucher_id == voucher.id)):
        raise BusinessError("ALREADY_REVERSED", "此傳票已建立沖銷傳票", 409)
    data = {"voucher_no": number, "voucher_date": voucher.voucher_date.isoformat(),
            "period_id": voucher.period_id, "description": "沖銷 " + voucher.voucher_no,
            "lines": [{"account_id": x.account_id, "debit": Decimal(x.credit_minor) / 100,
                       "credit": Decimal(x.debit_minor) / 100, "description": x.description} for x in voucher.lines]}
    result = save_voucher(data, actor_id, commit=False)
    result.reversed_voucher_id = voucher.id
    log(actor_id, "REVERSE_CREATE", "voucher", result.id, after={"original_id": voucher.id})
    db.session.commit()
    return result


def balances(as_of):
    rows = db.session.execute(select(Account, func.coalesce(func.sum(LedgerEntry.debit_minor), 0),
        func.coalesce(func.sum(LedgerEntry.credit_minor), 0)).outerjoin(
        LedgerEntry, (Account.id == LedgerEntry.account_id) & (LedgerEntry.entry_date <= as_of)
    ).group_by(Account.id).order_by(Account.code)).all()
    return [{"account": a, "debit": int(d), "credit": int(c), "net": int(d-c)} for a, d, c in rows]


def trial_balance(as_of):
    rows = []
    for b in balances(as_of):
        if b["net"]:
            rows.append({"code": b["account"].code, "name": b["account"].name,
                         "debit_minor": max(b["net"], 0), "credit_minor": max(-b["net"], 0)})
    return {"rows": rows, "debit_minor": sum(x["debit_minor"] for x in rows),
            "credit_minor": sum(x["credit_minor"] for x in rows)}


def income_statement(start, end):
    if start > end:
        raise BusinessError("INVALID_DATE", "起日不可晚於迄日")
    rows = db.session.execute(select(Account, func.coalesce(func.sum(LedgerEntry.debit_minor), 0),
        func.coalesce(func.sum(LedgerEntry.credit_minor), 0)).join(
        LedgerEntry, Account.id == LedgerEntry.account_id).where(
        LedgerEntry.entry_date.between(start, end), Account.type.in_(["REVENUE", "EXPENSE"])
    ).group_by(Account.id).order_by(Account.code)).all()
    result = [{"code": a.code, "name": a.name, "type": a.type,
               "amount_minor": int(c-d if a.type == "REVENUE" else d-c)} for a, d, c in rows]
    revenue = sum(x["amount_minor"] for x in result if x["type"] == "REVENUE")
    expense = sum(x["amount_minor"] for x in result if x["type"] == "EXPENSE")
    return {"rows": result, "revenue_minor": revenue, "expense_minor": expense,
            "profit_minor": revenue-expense}


def balance_sheet(as_of):
    entries = balances(as_of)
    totals = {t: 0 for t in ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE")}
    rows = []
    for b in entries:
        a = b["account"]
        value = b["net"] if a.type in ("ASSET", "EXPENSE") else -b["net"]
        totals[a.type] += value
        if value and a.type in ("ASSET", "LIABILITY", "EQUITY"):
            rows.append({"code": a.code, "name": a.name, "type": a.type, "amount_minor": value})
    profit = totals["REVENUE"] - totals["EXPENSE"]
    return {"rows": rows, "asset_minor": totals["ASSET"],
            "liability_minor": totals["LIABILITY"], "equity_minor": totals["EQUITY"] + profit,
            "unclosed_profit_minor": profit}


def ledger(account_id, start, end):
    opening = db.session.scalar(select(func.coalesce(func.sum(
        LedgerEntry.debit_minor - LedgerEntry.credit_minor), 0)).where(
        LedgerEntry.account_id == account_id, LedgerEntry.entry_date < start)) or 0
    entries = db.session.execute(select(LedgerEntry, Voucher.voucher_no).join(
        Voucher, Voucher.id == LedgerEntry.voucher_id).where(
        LedgerEntry.account_id == account_id, LedgerEntry.entry_date.between(start, end)
    ).order_by(LedgerEntry.entry_date, LedgerEntry.id)).all()
    running = int(opening)
    rows = []
    for entry, no in entries:
        running += entry.debit_minor - entry.credit_minor
        rows.append({"date": entry.entry_date.isoformat(), "voucher_no": no,
                     "debit_minor": entry.debit_minor, "credit_minor": entry.credit_minor,
                     "balance_minor": running})
    return {"opening_minor": int(opening), "rows": rows, "closing_minor": running}
