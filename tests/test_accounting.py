from datetime import date
import pytest
from sqlalchemy import select, func
from app import db
from app.models import Account, FiscalPeriod, LedgerEntry, Voucher
from app.services import BusinessError, balance_sheet, income_statement, post_voucher, reverse_voucher, save_voucher, transition, trial_balance


def make_voucher(app, no, debit, credit, amount):
    with app.app_context():
        codes = {a.code: a.id for a in db.session.scalars(select(Account))}
        v = save_voucher({"voucher_no": no, "voucher_date": "2026-01-15", "period_id": 1,
            "description": no, "lines": [{"account_id": codes[debit], "debit": amount, "credit": "0"},
                {"account_id": codes[credit], "debit": "0", "credit": amount}]}, 1)
        transition(v, "submit", 1)
        transition(v, "approve", 1)
        post_voucher(v, 1)
        return v.id


def test_demo_reports(app):
    make_voucher(app, "JV-001", "1001", "3001", "1000000")
    make_voucher(app, "JV-002", "6001", "1001", "100000")
    make_voucher(app, "JV-003", "1001", "4001", "300000")
    with app.app_context():
        trial = trial_balance(date(2026, 1, 31))
        income = income_statement(date(2026, 1, 1), date(2026, 1, 31))
        sheet = balance_sheet(date(2026, 1, 31))
        assert trial["debit_minor"] == trial["credit_minor"] == 130000000
        assert income["revenue_minor"] == 30000000
        assert income["expense_minor"] == 10000000
        assert income["profit_minor"] == 20000000
        assert sheet["asset_minor"] == sheet["equity_minor"] == 120000000
        assert sheet["liability_minor"] == 0


def test_invalid_lines_and_status(app):
    with app.app_context():
        ids = {a.code: a.id for a in db.session.scalars(select(Account))}
        base = {"voucher_no": "BAD", "voucher_date": "2026-01-15", "period_id": 1,
                "description": "invalid", "lines": [{"account_id": ids["1001"], "debit": "5", "credit": "0"},
                {"account_id": ids["3001"], "debit": "0", "credit": "4"}]}
        with pytest.raises(BusinessError, match="不平衡"):
            save_voucher(base, 1)
        base["lines"][1]["credit"] = "5"
        v = save_voucher(base, 1)
        with pytest.raises(BusinessError):
            post_voucher(v, 1)


def test_duplicate_post_and_closed_period(app):
    vid = make_voucher(app, "JV-001", "1001", "3001", "100")
    with app.app_context():
        v = db.session.get(Voucher, vid)
        with pytest.raises(BusinessError):
            post_voucher(v, 1)
        assert db.session.scalar(select(func.count()).select_from(LedgerEntry)) == 2
        p = db.session.get(FiscalPeriod, 1)
        p.status = "CLOSED"
        db.session.commit()
        with pytest.raises(BusinessError):
            save_voucher({"voucher_no": "JV-002", "voucher_date": "2026-01-15", "period_id": 1,
                "description": "closed", "lines": []}, 1)


def test_asset_transfer_not_expense(app):
    make_voucher(app, "JV-001", "1001", "3001", "1000000")
    make_voucher(app, "JV-004", "1501", "1001", "500000")
    with app.app_context():
        sheet = balance_sheet(date(2026, 1, 31))
        income = income_statement(date(2026, 1, 1), date(2026, 1, 31))
        assert sheet["asset_minor"] == 100000000
        assert income["expense_minor"] == 0


def test_api_auth_csrf_and_render(client, auth_client):
    assert auth_client.get("/dashboard").status_code == 200
    accounts_page = auth_client.get("/accounts")
    assert accounts_page.status_code == 200
    assert "資產（ASSET）" in accounts_page.get_data(as_text=True)
    assert "負債（LIABILITY）" in accounts_page.get_data(as_text=True)
    assert auth_client.get("/vouchers/new").status_code == 200
    assert auth_client.get("/accounts/1").status_code == 200
    assert auth_client.get("/reports/trial-balance").status_code == 200
    assert auth_client.get("/reports/balance-sheet").status_code == 200
    assert auth_client.post("/api/v1/vouchers", json={}).status_code == 400
    assert auth_client.get("/api/v1/accounts").status_code == 200


def test_edit_and_reverse(app):
    with app.app_context():
        ids = {a.code: a.id for a in db.session.scalars(select(Account))}
        data = {"voucher_no": "EDIT", "voucher_date": "2026-01-15", "period_id": 1,
            "description": "original", "lines": [{"account_id": ids["1001"], "debit": "100", "credit": "0"},
                {"account_id": ids["3001"], "debit": "0", "credit": "100"}]}
        v = save_voucher(data, 1)
        data["description"] = "changed"
        v = save_voucher(data, 1, v)
        assert v.description == "changed" and len(v.lines) == 2
        transition(v, "submit", 1)
        transition(v, "approve", 1)
        post_voucher(v, 1)
        rev = reverse_voucher(v, 1, "R-EDIT")
        transition(rev, "submit", 1)
        transition(rev, "approve", 1)
        post_voucher(rev, 1)
        assert trial_balance(date(2026, 1, 31))["debit_minor"] == 0
        with pytest.raises(BusinessError):
            reverse_voucher(v, 1, "R2-EDIT")


def test_api_workflow_and_mount(app, auth_client):
    with app.app_context():
        ids = {a.code: a.id for a in db.session.scalars(select(Account))}
    payload = {"voucher_no": "API-1", "voucher_date": "2026-01-15", "period_id": 1,
        "description": "API test", "lines": [{"account_id": ids["1001"], "debit": "25", "credit": "0"},
            {"account_id": ids["3001"], "debit": "0", "credit": "25"}]}
    response = auth_client.post("/api/v1/vouchers", json=payload, headers=auth_client.csrf_headers)
    assert response.status_code == 201
    vid = response.json["data"]["id"]
    patched = auth_client.patch(f"/api/v1/vouchers/{vid}", json={"description": "updated"}, headers=auth_client.csrf_headers)
    assert patched.status_code == 200 and patched.json["data"]["description"] == "updated"
    updated_account = auth_client.patch(f"/api/v1/accounts/{ids['1001']}", json={"name": "銀行存款"}, headers=auth_client.csrf_headers)
    assert updated_account.status_code == 200
    for action in ("submit", "approve", "post"):
        response = auth_client.post(f"/api/v1/vouchers/{vid}/{action}", headers=auth_client.csrf_headers)
        assert response.status_code == 200
    assert auth_client.get(f"/vouchers/{vid}").status_code == 200
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    mounted = Client(DispatcherMiddleware(Response("missing", status=404), {"/gl": app}), Response)
    response = mounted.get("/gl/login")
    assert response.status_code == 200
    assert b'/gl/static/app.css' in response.data


def test_post_failure_rolls_back(app):
    from sqlalchemy import event
    with app.app_context():
        ids = {a.code: a.id for a in db.session.scalars(select(Account))}
        v = save_voucher({"voucher_no": "FAIL", "voucher_date": "2026-01-15", "period_id": 1,
            "description": "rollback", "lines": [{"account_id": ids["1001"], "debit": "5", "credit": "0"},
                {"account_id": ids["3001"], "debit": "0", "credit": "5"}]}, 1)
        transition(v, "submit", 1)
        transition(v, "approve", 1)

        def fail_insert(mapper, connection, target):
            raise RuntimeError("simulated insert failure")

        event.listen(LedgerEntry, "before_insert", fail_insert)
        try:
            with pytest.raises(RuntimeError):
                post_voucher(v, 1)
        finally:
            event.remove(LedgerEntry, "before_insert", fail_insert)
        assert db.session.get(Voucher, v.id).status == "APPROVED"
        assert db.session.scalar(select(func.count()).select_from(LedgerEntry)) == 0


def test_unauthorized_api_and_csrf(app, auth_client):
    anonymous = app.test_client()
    assert anonymous.get("/api/v1/accounts").status_code == 401
    assert anonymous.post("/api/v1/vouchers", json={}).status_code == 401
    assert auth_client.post("/api/v1/vouchers", json={}).status_code == 400
    with app.app_context():
        from app.models import User
        viewer = User(username="viewer", role="VIEWER")
        viewer.set_password("viewer-password")
        db.session.add(viewer)
        db.session.commit()
    viewer_client = app.test_client()
    viewer_client.get("/login")
    with viewer_client.session_transaction() as s:
        token = s["_csrf"]
    viewer_client.post("/login", data={"username": "viewer", "password": "viewer-password", "csrf_token": token})
    assert viewer_client.post("/api/v1/vouchers", json={}, headers={"X-CSRF-Token": token}).status_code == 403


def test_cli_seed(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed-demo", "--actor", "admin", "--year", "2026"])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(LedgerEntry)) == 6
        assert trial_balance(date(2026, 1, 31))["debit_minor"] == 130000000


def test_init_db_command(tmp_path):
    from app import create_app
    from sqlalchemy import text
    application = create_app({"TESTING": True, "SECRET_KEY": "test-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (tmp_path / "fresh.db").as_posix()})
    runner = application.test_cli_runner()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    assert runner.invoke(args=["init-db"]).exit_code == 0
    with application.app_context():
        assert db.session.scalar(text("SELECT version_num FROM alembic_version")) == "b12ef3ec2083"


def test_local_mode_without_login(app):
    app.config.update(LOCAL_NO_AUTH=True, LOCAL_USER_ID=1)
    local_client = app.test_client()
    assert local_client.get("/").status_code == 302
    assert local_client.get("/dashboard").status_code == 200
    assert local_client.get("/admin/users").status_code == 200
    assert local_client.get("/login").headers["Location"].endswith("/dashboard")
    assert local_client.get("/api/v1/accounts").status_code == 200
    assert local_client.post("/api/v1/vouchers", json={}).status_code == 400
