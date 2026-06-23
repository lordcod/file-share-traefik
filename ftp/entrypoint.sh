#!/usr/bin/env bash
set -Eeuo pipefail

: "${FTP_USER:=ftpdeploy}"
: "${FTP_PASSWORD:?FTP_PASSWORD is required}"
: "${FTP_ROOT:=/srv/ftp}"
: "${FTP_UID:=1000}"
: "${FTP_GID:=1000}"
: "${FTP_GROUP:=ftpwww}"
: "${FTP_PASSIVE_MIN_PORT:=40000}"
: "${FTP_PASSIVE_MAX_PORT:=40100}"
: "${FTP_PASV_ADDRESS:=}"

mkdir -p "${FTP_ROOT}" /etc/vsftpd

if ! grep -qE "^${FTP_GROUP}:" /etc/group; then
  addgroup -S -g "${FTP_GID}" "${FTP_GROUP}"
fi

if ! id "${FTP_USER}" >/dev/null 2>&1; then
  adduser -D -u "${FTP_UID}" -G "${FTP_GROUP}" -h "${FTP_ROOT}" -s /sbin/nologin "${FTP_USER}"
fi

echo "${FTP_USER}:${FTP_PASSWORD}" | chpasswd

chown -R "${FTP_USER}:${FTP_GROUP}" "${FTP_ROOT}"
find "${FTP_ROOT}" -type d -exec chmod 02775 {} +
find "${FTP_ROOT}" -type f -exec chmod 0664 {} +

cat > /etc/vsftpd/vsftpd.conf <<EOF_CONF
listen=YES
listen_ipv6=NO
anonymous_enable=NO
local_enable=YES
write_enable=YES
local_umask=002
use_localtime=YES
xferlog_enable=YES
connect_from_port_20=YES
chroot_local_user=YES
allow_writeable_chroot=YES
local_root=${FTP_ROOT}
pasv_enable=YES
pasv_min_port=${FTP_PASSIVE_MIN_PORT}
pasv_max_port=${FTP_PASSIVE_MAX_PORT}
file_open_mode=0664
idle_session_timeout=3600
data_connection_timeout=600
ssl_enable=NO
pam_service_name=vsftpd
EOF_CONF

if [[ -n "${FTP_PASV_ADDRESS}" ]]; then
  echo "pasv_address=${FTP_PASV_ADDRESS}" >> /etc/vsftpd/vsftpd.conf
fi

exec "$@"