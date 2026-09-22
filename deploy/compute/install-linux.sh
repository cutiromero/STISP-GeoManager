#!/usr/bin/env bash
set -euo pipefail
# Run as root in the dedicated WSL Ubuntu distribution after Windows restart.
if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io ca-certificates
fi
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  systemctl enable --now docker
else
  service docker start
fi
docker info --format '{{.OSType}}'
