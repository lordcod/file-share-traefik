import os
import logging

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


logging.basicConfig(level=logging.INFO)

FTP_USER = os.getenv("FTP_USER", "ftpdeploy")
FTP_PASSWORD = os.environ["FTP_PASSWORD"]
FTP_ROOT = os.getenv("FTP_ROOT", "/srv/ftp")
FTP_PASSIVE_MIN_PORT = int(os.getenv("FTP_PASSIVE_MIN_PORT", "40000"))
FTP_PASSIVE_MAX_PORT = int(os.getenv("FTP_PASSIVE_MAX_PORT", "40100"))
FTP_PASV_ADDRESS = os.getenv("FTP_PASV_ADDRESS", "")


class AutoMkdirFTPHandler(FTPHandler):
    def _safe_mkdir_for_file(self, ftp_path):
        real_file = os.path.abspath(self.fs.ftp2fs(ftp_path))
        root = os.path.abspath(FTP_ROOT)

        logging.info("STOR requested ftp_path=%s real_file=%s",
                     ftp_path, real_file)

        if not real_file.startswith(root + os.sep):
            logging.warning("Blocked path outside FTP root: %s", real_file)
            return

        parent = os.path.dirname(real_file)
        os.makedirs(parent, exist_ok=True)
        logging.info("Created parent dir: %s", parent)

    def ftp_STOR(self, file, mode="w"):
        self._safe_mkdir_for_file(file)
        return super().ftp_STOR(file, mode)

    def ftp_CWD(self, path):
        real_dir = os.path.abspath(self.fs.ftp2fs(path))
        root = os.path.abspath(FTP_ROOT)

        logging.info("CWD requested path=%s real_dir=%s", path, real_dir)

        if real_dir.startswith(root + os.sep) or real_dir == root:
            os.makedirs(real_dir, exist_ok=True)
            logging.info("Created dir: %s", real_dir)

        return super().ftp_CWD(path)


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
