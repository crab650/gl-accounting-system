from datetime import date
import click
from flask import current_app
from sqlalchemy import select
from . import db
from .models import Account, FiscalPeriod, User, Voucher
from .services import post_voucher, save_voucher, transition


def register_commands(app):
    @app.cli.command("init-db")
    def init_db():
        """Apply Alembic migrations through the latest revision."""
        from flask_migrate import upgrade
        upgrade()
        click.echo("Database schema migrated to head")

    @app.cli.command("create-user")
    @click.option("--username", prompt=True)
    @click.option("--role", type=click.Choice(["ADMIN", "ACCOUNTANT", "APPROVER", "VIEWER"]), default="ADMIN")
    @click.password_option()
    def create_user(username, role, password):
        if len(password) < 12:
            raise click.ClickException("Password must have at least 12 characters")
        if db.session.scalar(select(User).where(User.username == username)):
            raise click.ClickException("Username already exists")
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created {username} ({role})")

    @app.cli.command("seed-demo")
    @click.option("--actor", required=True, help="Existing admin username")
    @click.option("--year", type=int, default=None, help="Demo fiscal year; defaults to current year")
    def seed_demo(actor, year):
        user = db.session.scalar(select(User).where(User.username == actor, User.role == "ADMIN"))
        if not user:
            raise click.ClickException("Create an ADMIN user first")
        year = year or date.today().year
        if db.session.scalar(select(Voucher).where(Voucher.voucher_no == "JV-001")):
            raise click.ClickException("DEMO vouchers already exist")
        period = db.session.scalar(select(FiscalPeriod).where(FiscalPeriod.fiscal_year == year, FiscalPeriod.period_no == 1))
        if not period:
            period = FiscalPeriod(fiscal_year=year, period_no=1, start_date=date(year, 1, 1), end_date=date(year, 12, 31))
            db.session.add(period)
            db.session.flush()
        if period.status != "OPEN":
            raise click.ClickException("Demo period is closed")
        specs = [("1001", "銀行存款", "ASSET"), ("1501", "生產設備", "ASSET"),
                 ("3001", "資本", "EQUITY"), ("4001", "銷貨收入", "REVENUE"),
                 ("6001", "水電費", "EXPENSE")]
        accounts = {}
        for code, name, kind in specs:
            account = db.session.scalar(select(Account).where(Account.code == code))
            if not account:
                account = Account(code=code, name=name, type=kind,
                    normal_side="DEBIT" if kind in ("ASSET", "EXPENSE") else "CREDIT")
                db.session.add(account)
                db.session.flush()
            accounts[code] = account.id
        db.session.commit()
        cases = [("JV-001", "資本投入", "1001", "3001", "1000000"),
                 ("JV-002", "水電費", "6001", "1001", "100000"),
                 ("JV-003", "銷貨收入", "1001", "4001", "300000")]
        for no, desc, debit, credit, amount in cases:
            voucher = save_voucher({"voucher_no": no, "voucher_date": date(year, 1, 15).isoformat(),
                "period_id": period.id, "description": desc, "lines": [
                    {"account_id": accounts[debit], "debit": amount, "credit": "0"},
                    {"account_id": accounts[credit], "debit": "0", "credit": amount}]}, user.id)
            transition(voucher, "submit", user.id)
            transition(voucher, "approve", user.id)
            post_voucher(voucher, user.id)
        click.echo("DEMO seeded: JV-001, JV-002, JV-003")
