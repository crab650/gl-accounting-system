from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from . import db


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Account(db.Model):
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    normal_side = db.Column(db.String(6), nullable=False)
    postable = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    report_group = db.Column(db.String(40))


class FiscalPeriod(db.Model):
    __tablename__ = "fiscal_periods"
    id = db.Column(db.Integer, primary_key=True)
    fiscal_year = db.Column(db.Integer, nullable=False)
    period_no = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), default="OPEN", nullable=False)
    __table_args__ = (db.UniqueConstraint("fiscal_year", "period_no"),)


class Voucher(db.Model):
    __tablename__ = "vouchers"
    id = db.Column(db.Integer, primary_key=True)
    voucher_no = db.Column(db.String(40), unique=True, nullable=False)
    voucher_date = db.Column(db.Date, nullable=False)
    period_id = db.Column(db.Integer, db.ForeignKey("fiscal_periods.id"), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    source_type = db.Column(db.String(30), default="MANUAL", nullable=False)
    source_ref = db.Column(db.String(100))
    status = db.Column(db.String(12), default="DRAFT", nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime(timezone=True))
    posted_at = db.Column(db.DateTime(timezone=True))
    reversed_voucher_id = db.Column(db.Integer, db.ForeignKey("vouchers.id"), unique=True)
    lines = db.relationship("VoucherLine", backref="voucher", cascade="all, delete-orphan", order_by="VoucherLine.line_no")
    period = db.relationship("FiscalPeriod")
    __table_args__ = (
        db.Index("ix_vouchers_date_status", "voucher_date", "status"),
        db.Index("ix_vouchers_period_status", "period_id", "status"),
    )


class VoucherLine(db.Model):
    __tablename__ = "voucher_lines"
    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey("vouchers.id"), nullable=False)
    line_no = db.Column(db.Integer, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    description = db.Column(db.String(500), default="", nullable=False)
    debit_minor = db.Column(db.BigInteger, default=0, nullable=False)
    credit_minor = db.Column(db.BigInteger, default=0, nullable=False)
    account = db.relationship("Account")
    __table_args__ = (
        db.UniqueConstraint("voucher_id", "line_no"),
        db.Index("ix_voucher_lines_account", "account_id"),
        db.CheckConstraint("debit_minor >= 0 AND credit_minor >= 0"),
        db.CheckConstraint("(debit_minor > 0 AND credit_minor = 0) OR (credit_minor > 0 AND debit_minor = 0)"),
    )


class LedgerEntry(db.Model):
    __tablename__ = "ledger_entries"
    id = db.Column(db.Integer, primary_key=True)
    voucher_line_id = db.Column(db.Integer, db.ForeignKey("voucher_lines.id"), unique=True, nullable=False)
    voucher_id = db.Column(db.Integer, db.ForeignKey("vouchers.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    entry_date = db.Column(db.Date, nullable=False)
    period_id = db.Column(db.Integer, db.ForeignKey("fiscal_periods.id"), nullable=False)
    debit_minor = db.Column(db.BigInteger, nullable=False)
    credit_minor = db.Column(db.BigInteger, nullable=False)
    __table_args__ = (
        db.Index("ix_ledger_account_date", "account_id", "entry_date", "id"),
        db.Index("ix_ledger_period_account", "period_id", "account_id"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(40), nullable=False)
    entity_type = db.Column(db.String(30), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    before_json = db.Column(db.JSON)
    after_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (db.Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),)


