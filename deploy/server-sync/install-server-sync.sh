#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请以 root 身份运行此安装脚本。" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -d -m 700 /etc/geomanager-sync /var/lib/geomanager-sync /var/lib/geomanager-sync/backups
install -m 700 "${ROOT}/geomanager-sync.sh" /usr/local/sbin/geomanager-sync
install -m 644 "${ROOT}/geomanager-sync.service" /etc/systemd/system/geomanager-sync.service
install -m 644 "${ROOT}/geomanager-sync.timer" /etc/systemd/system/geomanager-sync.timer

if [[ ! -e /etc/geomanager-sync/config.env ]]; then
  install -m 600 "${ROOT}/config.env.example" /etc/geomanager-sync/config.env
  echo "已创建 /etc/geomanager-sync/config.env，请先填写服务器实际路径和代理。" >&2
fi

systemctl daemon-reload
systemctl enable geomanager-sync.timer
systemctl start geomanager-sync.timer
echo "已安装每日 04:00 定时器。首次更新前请执行："
echo "  geomanager-sync check"
echo "检查无误后执行："
echo "  geomanager-sync apply"
