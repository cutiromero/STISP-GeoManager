#!/usr/bin/env bash
# Build a separate candidate binary; never replace or restart a running service.
set -euo pipefail
ROOT=${1:?absolute isolated build directory required}
SOURCE_ZIP=${2:?official v0.8.2 source zip required}
SQLITE_INCLUDE=${3:?existing sqlite development header directory required}
case "$ROOT" in /*) ;; *) echo 'An absolute build directory is required' >&2; exit 2;; esac
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
GO_SHA=aac1b08a0fb0c4e0a7c1555beb7b59180b05dfc5a3d62e40e9de90cd42f88235
SOURCE_SHA=54d68abfb2e25678072e82ca49946e2397f686b07ffc09031473bae8535af113
PATCH_SHA=632dffed5c9cb542d238d82fc9ea989c6962ca4b86733c2b06b394563803765f
printf '%s  %s\n' "$SOURCE_SHA" "$SOURCE_ZIP" | sha256sum --check --status
printf '%s  %s\n' "$PATCH_SHA" "$SCRIPT_DIR/weknora-sqlite-wiki.patch" | sha256sum --check --status
test -f "$SQLITE_INCLUDE/sqlite3.h"
mkdir -p "$ROOT/toolchain" "$ROOT/build-cache" "$ROOT/modules"
GO_TAR="$ROOT/toolchain/go1.26.0.linux-amd64.tar.gz"
if [ ! -f "$GO_TAR" ]; then
  curl --fail --location --retry 2 https://mirrors.aliyun.com/golang/go1.26.0.linux-amd64.tar.gz -o "$GO_TAR"
fi
printf '%s  %s\n' "$GO_SHA" "$GO_TAR" | sha256sum --check --status
if [ ! -x "$ROOT/toolchain/go/bin/go" ]; then tar -xzf "$GO_TAR" -C "$ROOT/toolchain"; fi
SOURCE_HOME="$ROOT/source-stisp1"
if [ ! -f "$SOURCE_HOME/patch.sha256" ]; then
  if [ ! -d "$SOURCE_HOME" ]; then
    mkdir "$SOURCE_HOME"
    unzip -q "$SOURCE_ZIP" -d "$SOURCE_HOME"
  fi
  (cd "$SOURCE_HOME/WeKnora-0.8.2" && git apply --check "$SCRIPT_DIR/weknora-sqlite-wiki.patch" && git apply "$SCRIPT_DIR/weknora-sqlite-wiki.patch")
  printf '%s\n' "$PATCH_SHA" > "$SOURCE_HOME/patch.sha256"
fi
test "$(cat "$SOURCE_HOME/patch.sha256")" = "$PATCH_SHA"
cd "$SOURCE_HOME/WeKnora-0.8.2"
export PATH="$ROOT/toolchain/go/bin:$PATH"
export GOCACHE="$ROOT/build-cache" GOMODCACHE="$ROOT/modules" GOTOOLCHAIN=local CGO_ENABLED=1
export CGO_CFLAGS="-I$SQLITE_INCLUDE" GOPROXY=https://goproxy.cn,direct
go version
go test -tags sqlite_fts5 ./internal/application/repository -run TestLiteWikiSQLiteCompatibility -count=1
go build -p 4 -tags sqlite_fts5 -ldflags="-w -s -X github.com/Tencent/WeKnora/internal/handler.Version=v0.8.2-stisp1 -X github.com/Tencent/WeKnora/internal/handler.Edition=lite -X github.com/Tencent/WeKnora/internal/handler.CommitID=3e8b0bf" -o "$ROOT/WeKnora-lite.new" ./cmd/server
sha256sum "$ROOT/WeKnora-lite.new"
