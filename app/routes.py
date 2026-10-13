from datetime import date, datetime, timezone
from functools import wraps
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from . import db
from .account_types import ACCOUNT_TYPES
from .models import Account, AuditLog, FiscalPeriod, LedgerEntry, User, Voucher, VoucherLine
from .services import (BusinessError, balance_sheet, income_statement, ledger, log,
                       money_text, open_period, parse_date, post_voucher, reverse_voucher,
                       save_voucher, transition, trial_balance)

bp = Blueprint("gl", __name__)
ROLES = ("ADMIN", "ACCOUNTANT", "APPROVER", "VIEWER")
TYPES = tuple(ACCOUNT_TYPES)


@bp.app_template_filter("money")
def money_filter(value):
    return money_text(value)


@bp.app_template_filter("account_type_label")
def account_type_label(value):
    return ACCOUNT_TYPES.get(value, {}).get("label", value)


@bp.app_errorhandler(BusinessError)
def business_error(error):
    db.session.rollback()
    if request.path.startswith("/api/"):
        return jsonify(error={"code": error.code, "message": error.message}), error.status
    flash(error.message, "danger")
    return redirect(request.referrer or url_for("gl.dashboard"))


@bp.app_errorhandler(IntegrityError)
def integrity_error(error):
    db.session.rollback()
    if request.path.startswith("/api/"):
        return jsonify(error={"code": "CONFLICT", "message": "資料衝突或不符合約束"}), 409
    flash("資料衝突或不符合約束", "danger")
    return redirect(request.referrer or url_for("gl.dashboard"))


def current_user():
    if current_app.config["LOCAL_NO_AUTH"]:
        uid = current_app.config["LOCAL_USER_ID"]
        user = db.session.get(User, uid) if uid else None
        return user if user and user.is_active else None
    uid = session.get("user_id")
    user = db.session.get(User, uid) if uid else None
    return user if user and user.is_active else None


@bp.app_context_processor
def inject_user():
    return {"current_user": current_user(), "local_no_auth": current_app.config["LOCAL_NO_AUTH"],
            "account_types": ACCOUNT_TYPES}


def require(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify(error={"code": "UNAUTHORIZED", "message": "請先登入"}), 401
                return redirect(url_for("gl.login"))
            if roles and user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_app.config["LOCAL_NO_AUTH"]:
        return redirect(url_for("gl.dashboard"))
    if request.method == "POST":
        user = db.session.scalar(select(User).where(User.username == request.form.get("username", "")))
        if user and user.is_active and user.check_password(request.form.get("password", "")):
            csrf = session.get("_csrf")
            session.clear()
            session["user_id"] = user.id
            session["_csrf"] = csrf
            log(user.id, "LOGIN", "user", user.id)
            db.session.commit()
            return redirect(url_for("gl.dashboard"))
        flash("帳號或密碼錯誤", "danger")
    return render_template("login.html")


@bp.post("/logout")
@require()
def logout():
    session.clear()
    return redirect(url_for("gl.login"))


@bp.get("/dashboard")
@require()
def dashboard():
    today = date.today()
    income = income_statement(today.replace(day=1), today)
    pending = db.session.scalar(select(func.count()).select_from(Voucher).where(Voucher.status == "SUBMITTED"))
    return render_template("dashboard.html", income=income, pending=pending)


def account_data(data=None):
    if data is None:
        data = (request.get_json(silent=True) or {}) if request.is_json else request.form
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    kind = str(data.get("type", "")).upper()
    if not code or not name or kind not in TYPES:
        raise BusinessError("INVALID_ACCOUNT", "請填寫科目代碼、名稱及有效類型")
    try:
        parent_id = int(data["parent_id"]) if data.get("parent_id") else None
    except (TypeError, ValueError):
        raise BusinessError("INVALID_PARENT", "父科目格式錯誤")
    parent = db.session.get(Account, parent_id) if parent_id else None
    if parent_id and (not parent or parent.type != kind):
        raise BusinessError("INVALID_PARENT", "父科目不存在或類型不同")
    return data, code, name, kind, parent_id


@bp.get("/accounts")
@require()
def accounts():
    return render_template("accounts.html", accounts=db.session.scalars(select(Account).order_by(Account.code)).all(), types=TYPES)


@bp.post("/accounts")
@require("ADMIN", "ACCOUNTANT")
def create_account_page():
    account = create_account()
    flash("科目已建立", "success")
    return redirect(url_for("gl.accounts"))


def create_account():
    data, code, name, kind, parent_id = account_data()
    if db.session.scalar(select(Account).where(Account.code == code)):
        raise BusinessError("DUPLICATE_ACCOUNT", "科目代碼已存在", 409)
    a = Account(code=code, name=name, type=kind, parent_id=parent_id,
                normal_side="DEBIT" if kind in ("ASSET", "EXPENSE") else "CREDIT",
                postable=str(data.get("postable", "true" if request.is_json else "false")).lower() in ("true", "1", "on"),
                active=str(data.get("active", "true" if request.is_json else "false")).lower() in ("true", "1", "on"),
                report_group=data.get("report_group"))
    db.session.add(a)
    db.session.flush()
    log(current_user().id, "CREATE", "account", a.id, after={"code": code, "name": name})
    db.session.commit()
    return a


@bp.route("/accounts/<int:account_id>", methods=["GET", "POST"])
@require("ADMIN", "ACCOUNTANT")
def edit_account_page(account_id):
    a = db.get_or_404(Account, account_id)
    if request.method == "POST":
        update_account(a)
        flash("科目已更新", "success")
        return redirect(url_for("gl.accounts"))
    return render_template("account_edit.html", account=a, accounts=db.session.scalars(select(Account).order_by(Account.code)).all(), types=TYPES)


def update_account(a, values=None):
    data, code, name, kind, parent_id = account_data(values)
    if parent_id == a.id:
        raise BusinessError("INVALID_PARENT", "科目不可成為自己的父科目")
    p = parent_id
    while p:
        if p == a.id:
            raise BusinessError("INVALID_PARENT", "科目階層不可循環")
        ancestor = db.session.get(Account, p)
        p = ancestor.parent_id if ancestor else None
    if db.session.scalar(select(Account).where(Account.code == code, Account.id != a.id)):
        raise BusinessError("DUPLICATE_ACCOUNT", "科目代碼已存在", 409)
    if db.session.scalar(select(func.count()).select_from(VoucherLine).where(VoucherLine.account_id == a.id)) and kind != a.type:
        raise BusinessError("ACCOUNT_IN_USE", "已使用科目不可修改類型", 409)
    if db.session.scalar(select(func.count()).select_from(Account).where(Account.parent_id == a.id)) and kind != a.type:
        raise BusinessError("ACCOUNT_HAS_CHILDREN", "有子科目的科目不可修改類型", 409)
    a.code, a.name, a.type, a.parent_id = code, name, kind, parent_id
    a.normal_side = "DEBIT" if kind in ("ASSET", "EXPENSE") else "CREDIT"
    a.postable = str(data.get("postable", "false")).lower() in ("true", "1", "on")
    a.active = str(data.get("active", "false")).lower() in ("true", "1", "on")
    a.report_group = data.get("report_group")
    log(current_user().id, "UPDATE", "account", a.id, after={"code": code, "name": name})
    db.session.commit()
    return a


@bp.get("/admin/periods")
@require()
def periods():
    return render_template("periods.html", periods=db.session.scalars(select(FiscalPeriod).order_by(FiscalPeriod.start_date)).all())


@bp.post("/admin/periods")
@require("ADMIN")
def create_period():
    data = (request.get_json(silent=True) or {}) if request.is_json else request.form
    start, end = parse_date(data.get("start_date")), parse_date(data.get("end_date"))
    if start > end or db.session.scalar(select(FiscalPeriod).where(FiscalPeriod.start_date <= end, FiscalPeriod.end_date >= start)):
        raise BusinessError("PERIOD_OVERLAP", "期間日期錯誤或與現有期間重疊")
    try:
        fiscal_year, period_no = int(data["fiscal_year"]), int(data["period_no"])
    except (KeyError, TypeError, ValueError):
        raise BusinessError("INVALID_PERIOD", "年度與期別須為整數")
    if not 1 <= period_no <= 13:
        raise BusinessError("INVALID_PERIOD", "期別須介於 1 到 13")
    p = FiscalPeriod(fiscal_year=fiscal_year, period_no=period_no, start_date=start, end_date=end)
    db.session.add(p)
    db.session.flush()
    log(current_user().id, "CREATE", "period", p.id)
    db.session.commit()
    if request.path.startswith("/api/"):
        return jsonify(data={"id": p.id}), 201
    return redirect(url_for("gl.periods"))


@bp.post("/admin/periods/<int:period_id>/toggle")
@require("ADMIN")
def toggle_period(period_id):
    p = db.get_or_404(FiscalPeriod, period_id)
    old = p.status
    p.status = "CLOSED" if old == "OPEN" else "OPEN"
    log(current_user().id, "PERIOD_" + p.status, "period", p.id, {"status": old}, {"status": p.status})
    db.session.commit()
    return redirect(url_for("gl.periods"))


@bp.get("/vouchers")
@require()
def vouchers():
    query = select(Voucher)
    status = request.args.get("status")
    if status:
        query = query.where(Voucher.status == status)
    rows = db.session.scalars(query.order_by(Voucher.voucher_date.desc(), Voucher.id.desc()).limit(100)).all()
    return render_template("vouchers.html", vouchers=rows, status=status)


@bp.route("/vouchers/new", methods=["GET", "POST"])
@require("ADMIN", "ACCOUNTANT")
def new_voucher():
    if request.method == "POST":
        v = save_voucher(form_voucher(), current_user().id)
        return redirect(url_for("gl.voucher_detail", voucher_id=v.id))
    return render_template("voucher_form.html", voucher=None, accounts=db.session.scalars(select(Account).where(Account.active == True, Account.postable == True).order_by(Account.code)).all(), periods=db.session.scalars(select(FiscalPeriod).where(FiscalPeriod.status == "OPEN").order_by(FiscalPeriod.start_date)).all())


def form_voucher():
    lines = []
    for account_id, debit, credit, desc in zip(request.form.getlist("account_id"), request.form.getlist("debit"), request.form.getlist("credit"), request.form.getlist("line_description")):
        if account_id or debit or credit:
            lines.append({"account_id": account_id, "debit": debit or "0", "credit": credit or "0", "description": desc})
    return {"voucher_no": request.form.get("voucher_no"), "voucher_date": request.form.get("voucher_date"), "period_id": request.form.get("period_id"), "description": request.form.get("description"), "lines": lines}


@bp.route("/vouchers/<int:voucher_id>", methods=["GET", "POST"])
@require()
def voucher_detail(voucher_id):
    v = db.get_or_404(Voucher, voucher_id)
    if request.method == "POST":
        if current_user().role not in ("ADMIN", "ACCOUNTANT"):
            abort(403)
        save_voucher(form_voucher(), current_user().id, v)
        return redirect(url_for("gl.voucher_detail", voucher_id=v.id))
    return render_template("voucher_detail.html", voucher=v, accounts=db.session.scalars(select(Account).where(Account.active == True).order_by(Account.code)).all(), periods=db.session.scalars(select(FiscalPeriod).where(FiscalPeriod.status == "OPEN")).all())


@bp.post("/vouchers/<int:voucher_id>/<action>")
@require()
def voucher_action(voucher_id, action):
    v = db.get_or_404(Voucher, voucher_id)
    user = current_user()
    allowed = {"submit": ("ADMIN", "ACCOUNTANT"), "redraft": ("ADMIN", "ACCOUNTANT"),
               "approve": ("ADMIN", "APPROVER"), "reject": ("ADMIN", "APPROVER"),
               "post": ("ADMIN", "ACCOUNTANT"), "reverse": ("ADMIN", "ACCOUNTANT")}
    if action not in allowed:
        abort(404)
    if user.role not in allowed[action]:
        abort(403)
    if action == "post":
        post_voucher(v, user.id)
    elif action == "reverse":
        number = request.form.get("voucher_no", "R-" + v.voucher_no)
        v = reverse_voucher(v, user.id, number)
    else:
        transition(v, action, user.id)
    return redirect(url_for("gl.voucher_detail", voucher_id=v.id))


@bp.get("/reports/<report>")
@require()
def report_page(report):
    today = date.today()
    as_of = parse_date(request.args.get("as_of", today.isoformat()))
    start = parse_date(request.args.get("from", today.replace(day=1).isoformat()))
    end = parse_date(request.args.get("to", today.isoformat()))
    account_id = request.args.get("account_id", type=int)
    if report == "trial-balance":
        data = trial_balance(as_of)
    elif report == "income-statement":
        data = income_statement(start, end)
    elif report == "balance-sheet":
        data = balance_sheet(as_of)
    elif report == "ledger":
        data = ledger(account_id, start, end) if account_id else None
    else:
        abort(404)
    return render_template("report.html", report=report, data=data, as_of=as_of, start=start, end=end,
                           generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                           account_id=account_id, accounts=db.session.scalars(select(Account).order_by(Account.code)).all())


@bp.get("/api/v1/accounts")
@require()
def api_accounts():
    return jsonify(data=[{"id": a.id, "code": a.code, "name": a.name, "type": a.type,
                          "active": a.active, "postable": a.postable} for a in db.session.scalars(select(Account).order_by(Account.code))])


@bp.post("/api/v1/accounts")
@require("ADMIN", "ACCOUNTANT")
def api_create_account():
    a = create_account()
    return jsonify(data={"id": a.id}), 201


@bp.get("/api/v1/accounts/<int:account_id>")
@require()
def api_account(account_id):
    a = db.get_or_404(Account, account_id)
    return jsonify(data={"id": a.id, "code": a.code, "name": a.name, "type": a.type,
                         "parent_id": a.parent_id, "active": a.active, "postable": a.postable})


@bp.patch("/api/v1/accounts/<int:account_id>")
@require("ADMIN", "ACCOUNTANT")
def api_update_account(account_id):
    a = db.get_or_404(Account, account_id)
    values = {"code": a.code, "name": a.name, "type": a.type, "parent_id": a.parent_id,
              "active": a.active, "postable": a.postable, "report_group": a.report_group}
    values.update(request.get_json() or {})
    a = update_account(a, values)
    return jsonify(data={"id": a.id})


def voucher_json(v):
    return {"id": v.id, "voucher_no": v.voucher_no, "voucher_date": v.voucher_date.isoformat(),
            "period_id": v.period_id, "description": v.description, "status": v.status,
            "lines": [{"account_id": x.account_id, "debit_minor": x.debit_minor,
                       "credit_minor": x.credit_minor, "description": x.description} for x in v.lines]}


@bp.route("/api/v1/vouchers", methods=["GET", "POST"])
@require()
def api_vouchers():
    if request.method == "POST":
        if current_user().role not in ("ADMIN", "ACCOUNTANT"):
            abort(403)
        v = save_voucher(request.get_json() or {}, current_user().id)
        return jsonify(data=voucher_json(v)), 201
    query = select(Voucher)
    if request.args.get("status"):
        query = query.where(Voucher.status == request.args["status"])
    return jsonify(data=[voucher_json(v) for v in db.session.scalars(query.order_by(Voucher.id.desc()).limit(100))])


@bp.route("/api/v1/vouchers/<int:voucher_id>", methods=["GET", "PATCH"])
@require()
def api_voucher(voucher_id):
    v = db.get_or_404(Voucher, voucher_id)
    if request.method == "PATCH":
        if current_user().role not in ("ADMIN", "ACCOUNTANT"):
            abort(403)
        from decimal import Decimal
        values = {"voucher_no": v.voucher_no, "voucher_date": v.voucher_date.isoformat(),
                  "period_id": v.period_id, "description": v.description,
                  "lines": [{"account_id": x.account_id, "debit": str(Decimal(x.debit_minor) / 100),
                             "credit": str(Decimal(x.credit_minor) / 100), "description": x.description}
                            for x in v.lines]}
        values.update(request.get_json() or {})
        v = save_voucher(values, current_user().id, v)
    return jsonify(data=voucher_json(v))


@bp.post("/api/v1/vouchers/<int:voucher_id>/<action>")
@require()
def api_voucher_action(voucher_id, action):
    v = db.get_or_404(Voucher, voucher_id)
    user = current_user()
    allowed = {"submit": ("ADMIN", "ACCOUNTANT"), "redraft": ("ADMIN", "ACCOUNTANT"),
               "approve": ("ADMIN", "APPROVER"), "reject": ("ADMIN", "APPROVER"),
               "post": ("ADMIN", "ACCOUNTANT"), "reverse": ("ADMIN", "ACCOUNTANT")}
    if action not in allowed:
        abort(404)
    if user.role not in allowed[action]:
        abort(403)
    if action == "post":
        v = post_voucher(v, user.id)
    elif action == "reverse":
        v = reverse_voucher(v, user.id, (request.get_json() or {}).get("voucher_no", "R-" + v.voucher_no))
    else:
        v = transition(v, action, user.id)
    return jsonify(data=voucher_json(v))


@bp.get("/api/v1/reports/<report>")
@require()
def api_reports(report):
    today = date.today().isoformat()
    if report == "trial-balance":
        data = trial_balance(parse_date(request.args.get("as_of", today)))
    elif report == "balance-sheet":
        data = balance_sheet(parse_date(request.args.get("as_of", today)))
    elif report == "income-statement":
        data = income_statement(parse_date(request.args.get("from", today)), parse_date(request.args.get("to", today)))
    elif report == "ledger":
        account_id = request.args.get("account_id", type=int)
        if not account_id or not db.session.get(Account, account_id):
            raise BusinessError("INVALID_ACCOUNT", "請提供有效科目")
        data = ledger(account_id, parse_date(request.args.get("from", today)), parse_date(request.args.get("to", today)))
    else:
        abort(404)
    return jsonify(data=data)


@bp.get("/admin/audit")
@require("ADMIN")
def audit_page():
    logs = db.session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
    return render_template("audit.html", logs=logs)


@bp.route("/admin/users", methods=["GET", "POST"])
@require("ADMIN")
def users_page():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        if not username or len(password) < 12 or role not in ROLES:
            raise BusinessError("INVALID_USER", "請提供帳號、至少 12 字元密碼及有效角色")
        if db.session.scalar(select(User).where(User.username == username)):
            raise BusinessError("DUPLICATE_USER", "帳號已存在", 409)
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        log(current_user().id, "CREATE", "user", user.id, after={"username": username, "role": role})
        db.session.commit()
        return redirect(url_for("gl.users_page"))
    return render_template("users.html", users=db.session.scalars(select(User).order_by(User.username)).all(), roles=ROLES)
