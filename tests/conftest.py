from datetime import date
import pytest
from app import create_app, db
from app.models import Account, FiscalPeriod, User


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "SECRET_KEY": "test-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (tmp_path / "test.db").as_posix()})
    with application.app_context():
        db.create_all()
        user = User(username="admin", role="ADMIN")
        user.set_password("test-password")
        db.session.add(user)
        db.session.add(FiscalPeriod(fiscal_year=2026, period_no=1,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
        for code, name, kind in [("1001", "銀行", "ASSET"), ("1501", "設備", "ASSET"),
                                 ("3001", "資本", "EQUITY"), ("4001", "收入", "REVENUE"),
                                 ("6001", "費用", "EXPENSE")]:
            db.session.add(Account(code=code, name=name, type=kind,
                normal_side="DEBIT" if kind in ("ASSET", "EXPENSE") else "CREDIT"))
        db.session.commit()
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    client.get("/login")
    with client.session_transaction() as s:
        token = s["_csrf"]
    response = client.post("/login", data={"username": "admin", "password": "test-password", "csrf_token": token})
    assert response.status_code == 302
    client.csrf_headers = {"X-CSRF-Token": token}
    return client
