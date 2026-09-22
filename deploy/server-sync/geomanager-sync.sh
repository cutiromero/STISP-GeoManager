#!/usr/bin/env bash
set -Eeuo pipefail

# Safe, image based production updater for GeoManager.
#
# The script deliberately performs exactly one bounded GitHub preflight before
# it changes a container.  If GitHub or GHCR cannot be reached, it records a
# failure and exits without stopping, pulling, or recreating the service.

CONFIG_FILE="${GEOMANAGER_SYNC_CONFIG:-/etc/geomanager-sync/config.env}"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

REPOSITORY="${GEOMANAGER_REPOSITORY:-spAurora/GeoManager}"
IMAGE="${GEOMANAGER_IMAGE:-ghcr.io/spaurora/geomanager}"
CONTAINER="${GEOMANAGER_CONTAINER:-geomanager}"
HOST_PORT="${GEOMANAGER_HOST_PORT:-6007}"
CONTAINER_PORT="${GEOMANAGER_CONTAINER_PORT:-8000}"
CONFIG_DIR="${GEOMANAGER_CONFIG_DIR:-/srv/geomanager/config}"
DATA_VOLUME="${GEOMANAGER_DATA_VOLUME:-huyang-data}"
HEALTH_URL="${GEOMANAGER_HEALTH_URL:-http://127.0.0.1:${HOST_PORT}/api/health/}"
PROXY_URL="${GEOMANAGER_PROXY_URL:-}"
GITHUB_TOKEN_FILE="${GEOMANAGER_GITHUB_TOKEN_FILE:-/etc/geomanager-sync/github-token}"
GHCR_USERNAME="${GEOMANAGER_GHCR_USERNAME:-}"
GHCR_TOKEN_FILE="${GEOMANAGER_GHCR_TOKEN_FILE:-/etc/geomanager-sync/ghcr-token}"
STATE_DIR="${GEOMANAGER_STATE_DIR:-/var/lib/geomanager-sync}"
BACKUP_DIR="${GEOMANAGER_BACKUP_DIR:-${STATE_DIR}/backups}"
LOCK_FILE="${GEOMANAGER_LOCK_FILE:-${STATE_DIR}/update.lock}"
HEALTH_ATTEMPTS="${GEOMANAGER_HEALTH_ATTEMPTS:-12}"
HEALTH_DELAY="${GEOMANAGER_HEALTH_DELAY:-5}"

mkdir -p "$STATE_DIR" "$BACKUP_DIR"
umask 077

if [[ -n "$PROXY_URL" ]]; then
  # Docker CLI and curl both use the same approved server proxy. There is no
  # direct-network fallback when a proxy is configured.
  export HTTP_PROXY="$PROXY_URL" HTTPS_PROXY="$PROXY_URL"
fi

timestamp() { date -u +%Y%m%dT%H%M%SZ; }
log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

write_result() {
  local status="$1" reason="$2" commit="${3:-}" backup="${4:-}"
  local tmp="${STATE_DIR}/last-result.json.tmp"
  cat >"$tmp" <<EOF
{
  "status": "${status}",
  "reason": "${reason}",
  "repository": "${REPOSITORY}",
  "commit": "${commit}",
  "backup": "${backup}",
  "finishedAt": "$(date -u +%FT%TZ)"
}
EOF
  mv -f "$tmp" "${STATE_DIR}/last-result.json"
}

fail() {
  local reason="$1"
  write_result "failed" "$reason" "${COMMIT:-}" "${BACKUP_PATH:-}"
  log "更新已停止：${reason}"
  exit 1
}

network_args=()
if [[ -n "$PROXY_URL" ]]; then
  network_args+=(--proxy "$PROXY_URL")
fi

require_file() {
  local path="$1" label="$2"
  [[ -s "$path" ]] || fail "缺少${label}：${path}"
}

github_api() {
  local endpoint="$1"
  local -a auth=()
  if [[ -s "$GITHUB_TOKEN_FILE" ]]; then
    local token
    token="$(<"$GITHUB_TOKEN_FILE")"
    auth=(-H "Authorization: Bearer ${token}")
  fi
  curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
    "${network_args[@]}" -H 'Accept: application/vnd.github+json' \
    "${auth[@]}" "https://api.github.com/${endpoint}"
}

preflight() {
  command -v curl >/dev/null || fail "服务器缺少 curl，未执行更新"
  command -v docker >/dev/null || fail "服务器缺少 Docker，未执行更新"
  command -v python3 >/dev/null || fail "服务器缺少 python3，未执行更新"
  command -v flock >/dev/null || fail "服务器缺少 flock，未执行更新"
  require_file "$GHCR_TOKEN_FILE" "GHCR 只读令牌文件"
  [[ -n "$GHCR_USERNAME" ]] || fail "未配置 GHCR 用户名，未执行更新"

  local response
  if ! response="$(github_api "repos/${REPOSITORY}/commits/main")"; then
    fail "无法连接 GitHub 或仓库权限不足，未执行更新"
  fi
  COMMIT="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])' 2>/dev/null || true)"
  [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "GitHub 未返回有效 main 提交，未执行更新"
  RELEASE_TAG="${COMMIT:0:7}"

  # Authenticate once, without putting the token in the process arguments.
  if ! docker login ghcr.io --username "$GHCR_USERNAME" --password-stdin <"$GHCR_TOKEN_FILE" >/dev/null 2>&1; then
    fail "无法登录 GHCR，未执行更新"
  fi
  if ! docker manifest inspect "${IMAGE}:${RELEASE_TAG}" >/dev/null 2>&1; then
    fail "GHCR 中没有提交 ${RELEASE_TAG} 的镜像，未执行更新"
  fi
  log "网络预检通过，目标镜像 ${IMAGE}:${RELEASE_TAG}"
}

backup_current() {
  BACKUP_PATH="${BACKUP_DIR}/$(timestamp)-${COMMIT}"
  mkdir -p "$BACKUP_PATH"
  if docker inspect "$CONTAINER" >"${BACKUP_PATH}/container.inspect.json" 2>/dev/null; then
    docker inspect -f '{{.Config.Image}}' "$CONTAINER" >"${BACKUP_PATH}/current-image.txt" || true
  fi
  [[ -d "$CONFIG_DIR" ]] || fail "配置目录不存在：${CONFIG_DIR}"
  tar -C "$CONFIG_DIR" -czf "${BACKUP_PATH}/config.tar.gz" .
  if docker volume inspect "$DATA_VOLUME" >/dev/null 2>&1; then
    local mountpoint
    mountpoint="$(docker volume inspect -f '{{.Mountpoint}}' "$DATA_VOLUME")"
    tar -C "$mountpoint" -czf "${BACKUP_PATH}/data-volume.tar.gz" .
  else
    fail "数据卷不存在：${DATA_VOLUME}"
  fi
}

run_new_container() {
  docker run -d --name "$CONTAINER" \
    --restart unless-stopped \
    -p "${HOST_PORT}:${CONTAINER_PORT}" \
    -v "${CONFIG_DIR}:/config" \
    -v "${DATA_VOLUME}:/data" \
    "${IMAGE}:${RELEASE_TAG}" serve /config/app.toml >/dev/null
}

wait_for_health() {
  local attempt
  for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if curl --fail --silent --show-error --connect-timeout 3 --max-time 8 "$HEALTH_URL" >/dev/null; then
      return 0
    fi
    sleep "$HEALTH_DELAY"
  done
  return 1
}

rollback() {
  local old_name="$1"
  log "新容器健康检查失败，开始回滚"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  if docker inspect "$old_name" >/dev/null 2>&1; then
    docker rename "$old_name" "$CONTAINER" >/dev/null 2>&1 || true
    docker start "$CONTAINER" >/dev/null 2>&1 || true
  fi
}

apply_update() {
  exec 9>"$LOCK_FILE"
  flock -n 9 || fail "已有另一项更新正在运行，未执行并发更新"
  preflight
  backup_current

  local old_name="${CONTAINER}-previous-$(timestamp)"
  if docker inspect "$CONTAINER" >/dev/null 2>&1; then
    docker rename "$CONTAINER" "$old_name" >/dev/null
    docker stop "$old_name" >/dev/null
  fi
  if ! docker pull "${IMAGE}:${RELEASE_TAG}" >/dev/null; then
    rollback "$old_name"
    fail "镜像下载失败，已恢复旧容器"
  fi
  if ! run_new_container || ! wait_for_health; then
    rollback "$old_name"
    fail "新版本健康检查失败，已恢复旧容器"
  fi

  # Keep one known-good container for the next rollback, and remove older
  # leftovers only after the new version is healthy.
  docker rm "$old_name" >/dev/null 2>&1 || true
  write_result "success" "updated" "$COMMIT" "$BACKUP_PATH"
  log "更新成功：${IMAGE}:${RELEASE_TAG}"
}

check_only() {
  preflight
  write_result "success" "preflight-only" "$COMMIT" ""
  log "只读预检成功；没有停止或重建容器"
}

case "${1:-apply}" in
  check) check_only ;;
  apply) apply_update ;;
  *) echo "用法：$0 {check|apply}" >&2; exit 2 ;;
esac
