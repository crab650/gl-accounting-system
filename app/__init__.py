import os
import secrets
import hmac
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import HTTPException

db = SQLAlchemy()


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    data_dir = Path(os.environ.get("GL_DATA_DIR", app.instance_path)).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("GL_SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI="sqlite:///" + (data_dir / "gl.db").as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_NAME="gl_accounting_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("GL_SESSION_SECURE") == "1",
        WTF_CSRF_TIME_LIMIT=None,
        LOCAL_NO_AUTH=False,
        LOCAL_USER_ID=None,
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-only-secret"
        else:
            raise RuntimeError("Set GL_SECRET_KEY before starting the application")
    db.init_app(app)
    try:
        from flask_migrate import Migrate
        Migrate(app, db)
    except ImportError:
        pass

    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(32)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def csrf_check():
        if request.path.startswith("/api/") and not session.get("user_id") and not app.config["LOCAL_NO_AUTH"]:
            return None
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not app.config.get("DISABLE_CSRF"):
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("_csrf", "")
            if not expected or not hmac.compare_digest(supplied, expected):
                abort(400, description="CSRF token missing or invalid")

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def sqlite_foreign_keys(connection, _):
        if connection.__class__.__module__.startswith("sqlite3"):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

    from . import models  # noqa: F401
    from .routes import bp
    app.register_blueprint(bp)
    from .commands import register_commands
    register_commands(app)

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error={"code": error.name.upper().replace(" ", "_"), "message": error.description}), error.code
        return error

    @app.route("/")
    def index():
        return redirect(url_for("gl.dashboard"))

    return app
