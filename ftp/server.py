import os
import logging
import sqlite3
import time
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


logging.basicConfig(level=logging.INFO)

FTP_USER = os.getenv("FTP_USER", "ftpdeploy")
FTP_PASSWORD = os.environ["FTP_PASSWORD"]
FTP_ROOT = os.getenv("FTP_ROOT", "/srv/ftp")
FTP_PASSIVE_MIN_PORT = int(os.getenv("FTP_PASSIVE_MIN_PORT", "40000"))
FTP_PASSIVE_MAX_PORT = int(
    os.getenv("FTP_PASSIVE_MAX_PORT", "40019")
)
FTP_PASV_ADDRESS = os.getenv("FTP_PASV_ADDRESS", "")


class AutoMkdirFTPHandler(FTPHandler):
    def on_file_received(self, file):
        """Count successful transfers once per competition per UTC minute."""
        database = os.getenv("LIVE_DB")
        if not database:
            return
        try:
            parts = Path(file).resolve().relative_to(Path(FTP_ROOT).resolve()).parts
            if (len(parts) < 4 or len(parts[0]) != 4 or not parts[0].isascii()
                    or not parts[0].isdigit() or any(p.startswith((".", "_")) for p in parts[1:3])):
                return
            with sqlite3.connect(database, timeout=2) as db:
                db.execute("CREATE TABLE IF NOT EXISTS activity (competition TEXT, minute INTEGER, PRIMARY KEY (competition, minute))")
                minute = int(time.time() // 60)
                db.execute("INSERT OR IGNORE INTO activity VALUES (?, ?)", ("/".join(parts[:3]), minute))
                db.execute("DELETE FROM activity WHERE minute < ?", (minute - 1440,))
        except (OSError, ValueError, sqlite3.Error):
            logging.exception("Could not record live activity; FTP upload remains successful")

    def _to_real_path(self, path):
        root = os.path.abspath(FTP_ROOT)
        path = os.path.abspath(path)

        if path.startswith(root + os.sep) or path == root:
            return path

        return os.path.abspath(self.fs.ftp2fs(path))

    def ftp_CWD(self, path):
        real_dir = self._to_real_path(path)
        root = os.path.abspath(FTP_ROOT)

        logging.info("CWD requested path=%s real_dir=%s", path, real_dir)

        if real_dir.startswith(root + os.sep) or real_dir == root:
            os.makedirs(real_dir, exist_ok=True)
            logging.info("Created dir: %s", real_dir)

        return super().ftp_CWD(real_dir)

    def ftp_STOR(self, file, mode="w"):
        real_file = self._to_real_path(file)
        root = os.path.abspath(FTP_ROOT)

        logging.info("STOR requested file=%s real_file=%s", file, real_file)

        if real_file.startswith(root + os.sep):
            parent = os.path.dirname(real_file)
            os.makedirs(parent, exist_ok=True)
            logging.info("Created parent dir: %s", parent)

        return super().ftp_STOR(real_file, mode)


os.makedirs(FTP_ROOT, exist_ok=True)

authorizer = DummyAuthorizer()
authorizer.add_user(
    FTP_USER,
    FTP_PASSWORD,
    FTP_ROOT,
    perm="elradfmwMT"
)

handler = AutoMkdirFTPHandler
handler.authorizer = authorizer
handler.passive_ports = range(FTP_PASSIVE_MIN_PORT, FTP_PASSIVE_MAX_PORT + 1)

if FTP_PASV_ADDRESS:
    handler.masquerade_address = FTP_PASV_ADDRESS

server = FTPServer(("0.0.0.0", 21), handler)
server.serve_forever()
