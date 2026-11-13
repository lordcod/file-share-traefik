import base64
import binascii
import hmac
import html
import json
import logging
import os
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

ROOT = Path("/srv/ftp").resolve()
DB = os.getenv("LIVE_DB", "/srv/live/live.sqlite3")
USER = os.getenv("LIVE_ADMIN_USER", "admin")
PASSWORD = os.getenv("LIVE_ADMIN_PASSWORD", "")
CSRF = secrets.token_urlsafe(32)
ESC = html.escape
UNAVAILABLE_PAGE = Path(__file__).with_name("unavailable.html").read_text(encoding="utf-8")


def target(value):
    """Only existing HTML publications on this origin are valid targets."""
    parsed = urlsplit(value)
    path = unquote(parsed.path)
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
            or not path.startswith("/") or path.startswith("//")
            or "\\" in path or any(ord(c) < 32 for c in path)):
        raise ValueError("Укажите путь на этом сервере, например /2026/GNP/01/.")
    file = (ROOT / path.lstrip("/")).resolve()
    if not file.is_relative_to(ROOT):
        raise ValueError("Путь должен находиться внутри публикаций.")
    if file.is_dir():
        file /= "index.html"
    file = file.resolve()
    if not file.is_relative_to(ROOT):
        raise ValueError("Путь должен находиться внутри публикаций.")
    if file.suffix.lower() not in {".html", ".htm"} or not file.is_file():
        raise ValueError("HTML-страница не найдена. Проверьте путь и загрузку файлов.")
    relative = file.relative_to(ROOT).as_posix()
    if relative.split("/")[0] in {"live", "admin"}:
        raise ValueError("Этот путь зарезервирован.")
    return "/" + quote(relative, safe="/")


def catalog():
    try:
        return json.loads(Path("/srv/catalog/catalog.json").read_text(encoding="utf-8"))["competitions"]
    except (OSError, ValueError, KeyError):
        return []


def selection(mode=None, manual=None):
    with sqlite3.connect(DB, timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        state = dict(db.execute("SELECT key, value FROM settings"))
        if mode:
            state["mode"] = mode
        if manual is not None:
            state["manual"] = manual
        minute = int(time.time() // 60)
        db.execute("DELETE FROM activity WHERE minute < ?", (minute - 1439,))
        rows = db.execute("SELECT competition, COUNT(*) FROM activity WHERE minute BETWEEN ? AND ? GROUP BY competition ORDER BY COUNT(*) DESC, competition", (minute - 1439, minute)).fetchall()
        eligible = []
        for competition, score in rows:
            try:
                eligible.append((target("/" + competition + "/"), score))
            except (ValueError, OSError):
                continue
        previous = state.get("automatic", "")
        if eligible:
            leaders = [url for url, score in eligible if score == eligible[0][1]]
            state["automatic"] = previous if previous in leaders else leaders[0]
        elif previous:
            try:
                target(previous)
            except (ValueError, OSError):
                state["automatic"] = ""
        state.setdefault("mode", "auto")
        for key, value in state.items():
            db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
        state["current"] = state.get("manual" if state["mode"] == "manual" else "automatic", "")
        return state, eligible


STYLE = """body{margin:0;background:#f4f6f8;color:#172b3a;font:16px/1.6 system-ui,sans-serif}main{max-width:820px;margin:48px auto;padding:0 24px}h1{font-size:32px;line-height:1.2}h2{font-size:21px;margin-top:0}section{padding:26px 0;border-top:1px solid #cbd5df}a{color:#075ea5;text-underline-offset:3px;overflow-wrap:anywhere}label{display:block;font-weight:600;margin:16px 0 6px}input,select,button{font:inherit;box-sizing:border-box;max-width:100%;border:1px solid #9aaebe;border-radius:6px;padding:10px 12px}input,select{width:100%;background:white;color:#172b3a}button{cursor:pointer;background:#075ea5;color:white;border-color:#075ea5;margin-top:16px}button:hover{background:#034779}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #dd8700;outline-offset:3px}.muted{color:#516575}.notice{padding:12px;background:#fff1cf;color:#624200}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px 0;border-bottom:1px solid #dce3e9}td:last-child,th:last-child{text-align:right;font-variant-numeric:tabular-nums}small{display:block}::selection{background:#c6e5ff}@media(max-width:540px){main{margin:24px auto;padding:0 16px}h1{font-size:27px}}"""


def page(body):
    return f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Управление эфиром · SwimTab</title><style>{STYLE}</style><main>{body}</main></html>'


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send(self, code, body="", headers=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if not PASSWORD:
            self.send(503, page("<h1>Управление пока недоступно</h1><p>Администратор сервера должен настроить отдельный пароль входа.</p>"))
            return False
        try:
            scheme, encoded = self.headers.get("Authorization", "").split(" ", 1)
            supplied = base64.b64decode(encoded, validate=True)
            valid = scheme.lower() == "basic" and hmac.compare_digest(supplied, f"{USER}:{PASSWORD}".encode())
        except (ValueError, binascii.Error):
            valid = False
        if not valid:
            self.send(401, "Требуется вход", {"WWW-Authenticate": 'Basic realm="SwimTab Live", charset="UTF-8"'})
        return valid

    def admin(self, message="", code=200):
        state, activity = selection()
        entries = catalog()
        titles = {entry["url"]: entry["title"] for entry in entries}
        def link(url):
            return f'<a href="{ESC(url, quote=True)}">{ESC(titles.get(url, url))}</a>' if url else "Пока не определено"
        options = ''.join(f'<option value="{ESC(e["url"], quote=True)}">{ESC(e["title"])} — {ESC(e["id"])}</option>' for e in entries)
        token = f'<input type="hidden" name="csrf" value="{CSRF}">'
        rows = ''.join(f'<tr><td>{link(url)}</td><td>{score}</td></tr>' for url, score in activity)
        body = f'''<h1>Управление эфиром</h1><p class="muted">Постоянная ссылка для зрителей — <a href="/live">/live</a>.</p>
        {('<p class="notice" role="status">' + ESC(message) + '</p>') if message else ''}
        <section><h2>Сейчас: {"ручной режим" if state["mode"] == "manual" else "автоматический режим"}</h2><p>{link(state["current"])}</p>
        <p class="muted">Автоматический выбор: {link(state.get("automatic", ""))}</p></section>
        <section><h2>Закрепить соревнование</h2><p>Ручная ссылка останется выбранной до возвращения в автоматический режим.</p>
        <form method="post" action="/admin/live">{token}<input type="hidden" name="mode" value="manual">
        <label for="competition">Из каталога</label><select id="competition" name="competition"><option value="">Выберите соревнование</option>{options}</select>
        <label for="path">Или путь к публикации</label><input id="path" name="path" placeholder="/2026/GNP/01/" maxlength="2048" aria-describedby="path-help"><small id="path-help" class="muted">Если путь заполнен, используется он. Только страницы этого сервера.</small>
        <button type="submit">Закрепить ссылку</button></form></section>
        <section><h2>Автоматический выбор</h2><p>Лидирует соревнование с наибольшим числом активных минут FTP за последние 24 часа. При равенстве сохраняется прежний выбор. Без загрузок остаётся последняя ссылка.</p>
        <form method="post" action="/admin/live">{token}<input type="hidden" name="mode" value="auto"><button type="submit">Вернуть автоматический режим</button></form></section>
        <section><h2>Активность за 24 часа</h2>{('<table><thead><tr><th>Соревнование</th><th>Минуты</th></tr></thead><tbody>' + rows + '</tbody></table>') if rows else '<p class="muted">Загрузок для доступных публикаций пока нет.</p>'}<p><a href="/admin/live">Обновить данные</a></p></section>'''
        self.send(code, page(body))

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path in {"/live", "/live/"}:
                state, _ = selection()
                try:
                    url = target(state["current"]) if state["current"] else None
                except (ValueError, OSError):
                    url = None
                if url:
                    self.send(302, headers={"Location": url})
                else:
                    self.send(503, UNAVAILABLE_PAGE)
            elif path in {"/admin/live", "/admin/live/"}:
                if self.authorized():
                    self.admin("Настройки сохранены." if urlsplit(self.path).query == "saved=1" else "")
            else:
                self.send(404, "Не найдено")
        except (sqlite3.Error, OSError):
            logging.exception("Live request failed")
            self.send(503, "Сервис временно недоступен")

    def do_POST(self):
        if urlsplit(self.path).path != "/admin/live":
            self.send(404, "Не найдено")
            return
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                self.send(413, "Некорректный размер запроса")
                return
            values = parse_qs(self.rfile.read(length).decode("utf-8"), max_num_fields=8)
            if not hmac.compare_digest(values.get("csrf", [""])[0].encode(), CSRF.encode()):
                self.send(403, page('<h1>Форма устарела</h1><p><a href="/admin/live">Откройте страницу управления заново</a>.</p>'))
                return
            mode = values.get("mode", [""])[0]
            if mode not in {"auto", "manual"}:
                raise ValueError("Выберите режим управления.")
            manual = None
            if mode == "manual":
                value = values.get("path", [""])[0].strip() or values.get("competition", [""])[0]
                manual = target(value)
            selection(mode, manual)
            self.send(303, headers={"Location": "/admin/live?saved=1"})
        except (ValueError, OSError) as error:
            self.admin(str(error), 400)
        except sqlite3.Error:
            logging.exception("Could not save live settings")
            self.send(503, "Не удалось сохранить настройки. Повторите позже.")


if __name__ == "__main__":
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute("CREATE TABLE IF NOT EXISTS activity (competition TEXT, minute INTEGER, PRIMARY KEY (competition, minute))")
        db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    # Persist automatic selection even while nobody visits /live.
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    server.timeout = 30
    while True:
        try:
            selection()
        except (sqlite3.Error, OSError):
            logging.exception("Automatic selection failed")
        server.handle_request()
