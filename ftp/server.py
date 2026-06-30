import os
import logging
import json

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


logging.basicConfig(level=logging.INFO)

FTP_ROOT = os.getenv("FTP_ROOT", "/srv/ftp")
FTP_USERS_FILE = os.getenv("FTP_USERS_FILE", "/config/users.json")
FTP_PASSIVE_MIN_PORT = int(os.getenv("FTP_PASSIVE_MIN_PORT", "40000"))
FTP_PASSIVE_MAX_PORT = int(os.getenv("FTP_PASSIVE_MAX_PORT", "40100"))
FTP_PASV_ADDRESS = os.getenv("FTP_PASV_ADDRESS", "")


class AutoMkdirFTPHandler(FTPHandler):
    def _user_root(self):
        return os.path.abspath(self.fs.root)

    def _to_real_path(self, path):
        root = self._user_root()
        path = os.path.abspath(path)

        if path.startswith(root + os.sep) or path == root:
            return path

        return os.path.abspath(self.fs.ftp2fs(path))

    def ftp_CWD(self, path):
        real_dir = self._to_real_path(path)
        root = self._user_root()

        logging.info("CWD requested path=%s real_dir=%s", path, real_dir)

        if real_dir.startswith(root + os.sep) or real_dir == root:
            os.makedirs(real_dir, exist_ok=True)
            logging.info("Created dir: %s", real_dir)

        return super().ftp_CWD(real_dir)

    def ftp_STOR(self, file, mode="w"):
        real_file = self._to_real_path(file)
        root = self._user_root()

        logging.info("STOR requested file=%s real_file=%s", file, real_file)

        if real_file.startswith(root + os.sep):
            parent = os.path.dirname(real_file)
            os.makedirs(parent, exist_ok=True)
            logging.info("Created parent dir: %s", parent)

        return super().ftp_STOR(real_file, mode)


FTP_ROOT = os.path.abspath(FTP_ROOT)
os.makedirs(FTP_ROOT, exist_ok=True)

with open(FTP_USERS_FILE, encoding="utf-8") as users_file:
    users_config = json.load(users_file)

users = users_config.get("users", [])
if not users:
    raise ValueError(f"No FTP users configured in {FTP_USERS_FILE}")

authorizer = DummyAuthorizer()
configured_usernames = set()

for user in users:
    username = user["username"]
    password = user["password"]
    folder = user["folder"]
    permissions = user.get("permissions", "elradfmwMT")

    if username in configured_usernames:
        raise ValueError(f"Duplicate FTP username: {username}")

    home = os.path.abspath(os.path.join(FTP_ROOT, folder))
    if os.path.commonpath([FTP_ROOT, home]) != FTP_ROOT or home == FTP_ROOT:
        raise ValueError(f"Invalid folder for FTP user {username}: {folder}")

    os.makedirs(home, exist_ok=True)
    authorizer.add_user(username, password, home, perm=permissions)
    configured_usernames.add(username)
    logging.info("Configured FTP user=%s home=%s", username, home)

handler = AutoMkdirFTPHandler
handler.authorizer = authorizer
handler.passive_ports = range(FTP_PASSIVE_MIN_PORT, FTP_PASSIVE_MAX_PORT + 1)

if FTP_PASV_ADDRESS:
    handler.masquerade_address = FTP_PASV_ADDRESS

server = FTPServer(("0.0.0.0", 21), handler)
server.serve_forever()
