# 服务器自动同步

生产服务器使用 GitHub Actions 生成的 GHCR 镜像，不在服务器上重新构建源码。`deploy/server-sync/geomanager-sync.sh` 在更新前只做一次有超时的 GitHub/GHCR 预检；预检失败时写入 `/var/lib/geomanager-sync/last-result.json`、记录 systemd 日志并退出，绝不会停止现有容器或反复重试。

## 首次安装

服务器需要 Docker、`curl`、`python3` 和 `flock`。将 `deploy/server-sync/` 目录复制到服务器后执行：

```bash
sudo bash deploy/server-sync/install-server-sync.sh
sudoedit /etc/geomanager-sync/config.env
sudo install -m 600 /dev/null /etc/geomanager-sync/github-token
sudo install -m 600 /dev/null /etc/geomanager-sync/ghcr-token
```

两个令牌只保存在服务器：

- `github-token`：可读取 `spAurora/GeoManager` Contents 的 GitHub token；用于读取 `main` 最新提交。
- `ghcr-token`：可读取 `spAurora/geomanager` 容器包的 token；推荐只授予 `read:packages`，不要写入仓库或镜像。GitHub Container Registry 对某些账号仍要求 classic PAT；若 fine-grained token 被 GHCR 拒绝，只在服务器上使用一个最小权限的 classic PAT。

将服务器原有的国内代理、配置目录、数据卷、容器端口写入 `config.env`。配置目录必须是目录挂载，不能把单个 `app.toml` 文件挂载到 `/config/app.toml`，否则应用后台无法原子保存底图 Token。

先做只读网络检查：

```bash
sudo geomanager-sync check
sudo systemctl status geomanager-sync.timer
```

预检成功后再做首次更新：

```bash
sudo geomanager-sync apply
```

## 每日更新与失败报告

计时器按 `Asia/Shanghai` 每天 04:00 运行，并使用 `Persistent=true` 补执行错过的任务。查看最近结果：

```bash
sudo cat /var/lib/geomanager-sync/last-result.json
sudo journalctl -u geomanager-sync.service --since today --no-pager
```

更新顺序为：读取 `main` 提交 → 检查代理可达性 → 登录并检查 GHCR 镜像 → 备份配置和数据卷 → 拉取提交短 SHA 镜像 → 保留旧容器 → 启动新容器并健康检查。健康检查失败时恢复旧容器；GitHub/GHCR 网络预检失败时不进行任何容器变更。

## 底图 Token

Token 不进入 GitHub 仓库和 Docker 镜像。首次更新后，在服务器实际配置目录的 `app.toml` 中写入当前本机使用的 `mapbox_access_token` 和/或 `tianditu_access_token`，或在后台系统设置页保存。保存前后都保留配置备份；不要在聊天、命令行参数或日志中粘贴 Token。

服务器能访问 GitHub 只代表版本同步链路可用；Mapbox、天地图瓦片还必须分别从服务器出口测试。若服务器网络预检失败，脚本会报告失败原因并保持线上旧版本，等待人工处理。
