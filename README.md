# FTP + HTTPS file share behind existing Traefik

This repository is a Docker Compose version of the Ansible playbook:

- FTP upload into `./data`
- nginx serves the same `./data` directory as an HTTP file index
- existing Traefik exposes nginx as HTTPS using Docker labels
- FTP ports are published directly on the host

## Why FTP is not routed through Traefik by default

Traefik can route generic TCP connections, but FTP is not just one connection. In passive mode the client connects to port `21`, then opens a second data connection to one of the configured passive ports. Because of that, FTP is much easier and more predictable when port `21` and the passive range are published directly.

For a single-port upload protocol, prefer SFTP. An optional SFTP example is included in `docker-compose.sftp.example.yml`.

## Requirements

- Docker with the Compose plugin
- Existing Traefik container
- Traefik Docker provider enabled
- Traefik attached to a Docker network, for example `proxy`
- Traefik entrypoints named `web` and `websecure`
- Traefik certificate resolver matching `TRAEFIK_CERTRESOLVER`, for example `letsencrypt`
- DNS `A`/`AAAA` record for `HTTP_HOST` pointing to the server

## Setup

```bash
git clone <repo-url> file-share-traefik-compose
cd file-share-traefik-compose
make init
nano .env
```

Edit `.env`:

```env
HTTP_HOST=files.example.com
TRAEFIK_NETWORK=proxy
TRAEFIK_CERTRESOLVER=letsencrypt
FTP_USER=ftpdeploy
FTP_PASSWORD=use-a-strong-password
FTP_PASV_ADDRESS=203.0.113.10
```

Start the stack:

```bash
docker compose up -d --build
```

Or with Make:

```bash
make up
```

## Firewall / cloud security group

Open these inbound TCP ports:

```text
80, 443          handled by existing Traefik
21               FTP control port
40000-40100      FTP passive data ports
```

If you change `FTP_PASSIVE_MIN_PORT` / `FTP_PASSIVE_MAX_PORT`, update the firewall too.

## Usage

Upload via FTP:

```bash
ftp files.example.com
# user: ftpdeploy
# password: value from FTP_PASSWORD
```

Or with lftp:

```bash
lftp -u ftpdeploy,'use-a-strong-password' ftp://files.example.com
```

Then open:

```text
https://files.example.com
```

## Optional SFTP instead of FTP

SFTP is usually cleaner than FTP because it uses one TCP port. Start the optional SFTP service:

```bash
docker compose -f docker-compose.yml -f docker-compose.sftp.example.yml up -d
```

Default SFTP port is `2222` on the host:

```bash
sftp -P 2222 sftpdeploy@your-server
```

To route SFTP through Traefik TCP instead of direct `ports`, Traefik needs a dedicated TCP entrypoint, for example `:2222`. Since SSH has no TLS SNI, domain-based routing will not work for plain SSH/SFTP; `HostSNI(\`*\`)` catches all traffic on that entrypoint.

## Files

```text
.
├── docker-compose.yml
├── docker-compose.sftp.example.yml
├── .env.example
├── ftp/
│   ├── Dockerfile
│   └── entrypoint.sh
├── nginx/
│   └── default.conf
├── www/
│   └── index.html
├── examples/
│   └── traefik-static-sftp-entrypoint.yml
└── Makefile
```

## Notes

- `./data` is ignored by Git except for `.gitkeep`.
- nginx mounts `./data` read-only.
- FTP writes into the same `./data` directory.
- This FTP configuration has `ssl_enable=NO`, matching the original playbook. For sensitive uploads over the public Internet, prefer SFTP or enable FTPS explicitly.
