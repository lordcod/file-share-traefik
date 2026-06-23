import os
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


FTP_USER = os.getenv("FTP_USER")
FTP_PASSWORD = os.environ["FTP_PASSWORD"]
FTP_ROOT = os.getenv("FTP_ROOT", "/srv/ftp")
FTP_PASSIVE_MIN_PORT = int(os.getenv("FTP_PASSIVE_MIN_PORT", "40000"))
FTP_PASSIVE_MAX_PORT = int(os.getenv("FTP_PASSIVE_MAX_PORT", "40100"))
FTP_PASV_ADDRESS = os.getenv("FTP_PASV_ADDRESS", "")


class AutoMkdirFTPHandler(FTPHandler):
    def _mkdir_parent_for_ftp_path(self, path):
        real_path = self.fs.ftp2fs(path)
        root = os.path.abspath(FTP_ROOT)
        real_path = os.path.abspath(real_path)

        if not real_path.startswith(root + os.sep) and real_path != root:
            return

        parent = os.path.dirname(real_path)
        os.makedirs(parent, exist_ok=True)

    def ftp_CWD(self, path):
        real_path = self.fs.ftp2fs(path)
        root = os.path.abspath(FTP_ROOT)
        real_path = os.path.abspath(real_path)

        if real_path.startswith(root + os.sep) or real_path == root:
            os.makedirs(real_path, exist_ok=True)

        return super().ftp_CWD(path)

    def ftp_STOR(self, file, mode='w'):
        self._mkdir_parent_for_ftp_path(file)
        return super().ftp_STOR(file, mode)


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
