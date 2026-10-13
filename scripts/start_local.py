"""Local Windows launcher used by 啟動財務系統.bat."""

import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from werkzeug.serving import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def configure_local_environment():
    data_dir = Path(os.environ.get("GL_DATA_DIR", PROJECT_ROOT / "instance")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["GL_DATA_DIR"] = str(data_dir)
    if not os.environ.get("GL_SECRET_KEY"):
        secret_file = data_dir / ".secret_key"
        if not secret_file.exists():
            try:
                with secret_file.open("x", encoding="ascii") as stream:
                    stream.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
        os.environ["GL_SECRET_KEY"] = secret_file.read_text(encoding="ascii").strip()
    if not os.environ["GL_SECRET_KEY"]:
        raise RuntimeError("GL_SECRET_KEY is empty")


def ensure_local_operator(app):
    from sqlalchemy import select
    from app import db
    from app.models import User

    with app.app_context():
        suffix = 1
        while True:
            username = "local_operator" if suffix == 1 else f"local_operator_{suffix}"
            user = db.session.scalar(select(User).where(User.username == username))
            if user is None or (user.is_active and user.role == "ADMIN"):
                break
            suffix += 1
        if user is None:
            user = User(username=username, role="ADMIN")
            user.set_password(secrets.token_urlsafe(48))
            db.session.add(user)
            db.session.commit()
        app.config["LOCAL_USER_ID"] = user.id


def open_browser_when_ready(url):
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    if not webbrowser.open(url):
                        print(f"Could not open a browser automatically. Visit {url}", flush=True)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    print(f"The server did not become ready. Check the console, then visit {url}", flush=True)


def main():
    configure_local_environment()
    from app import create_app
    from flask_migrate import upgrade

    application = create_app({"LOCAL_NO_AUTH": True})
    with application.app_context():
        upgrade()
    ensure_local_operator(application)
    if "--check" in sys.argv[1:]:
        print("Startup check passed; local access needs no username or password.")
        return 0
    server = None
    port = None
    for candidate in (8765, 8766):
        try:
            with socket.create_connection(("127.0.0.1", candidate), timeout=0.25):
                continue
        except OSError:
            pass
        try:
            server = make_server("127.0.0.1", candidate, application)
            port = candidate
            break
        except SystemExit:
            continue
    if server is None:
        raise RuntimeError("Ports 8765 and 8766 are both in use")
    url = f"http://127.0.0.1:{port}/"
    print(f"Running at {url}", flush=True)
    print("Keep this window open while using the system. Press Ctrl+C to stop.", flush=True)
    browser_thread = None
    if "--no-browser" not in sys.argv[1:]:
        browser_thread = threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True)
        browser_thread.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print("\nStartup cancelled.")
        raise SystemExit(1)
