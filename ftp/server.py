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
    def ftp_CWD(self, path):
        real_path = self.fs.ftp2fs(path)
        if real_path.startswith(os.path.abspath(FTP_ROOT)):
            os.makedirs(real_path, exist_ok=True)
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
