# 2026-09-20 服务器同步核查

通过 `root@101.42.12.157:57865` 完成只读检查，未停止线上进程、未改写配置、未安装定时器。

## 现网形态

- 服务器是 AutoDL Ubuntu 容器，当前没有 Docker CLI 或 Docker daemon。
- GeoManager 由 Waitress 直接运行在 `0.0.0.0:6007`，启动脚本为 `/root/autodl-tmp/geomanager-start-6007.sh`。
- 当前源码目录为 `/root/autodl-tmp/geomanager-deploy-20260919`，不是 Git 工作树。
- 配置目录为 `/root/autodl-tmp/geomanager-config-20260919`，业务和科研数据目录为 `/root/autodl-tmp/geomanager-data-20260919`。
- `/etc/autodl-geomanager.sh` 负责启动 6007 服务。
- 线上健康接口正常；当前 Mapbox 与天地图 Token 均为空。

## 网络结论

服务器未配置 `HTTP_PROXY`/`HTTPS_PROXY`，执行一次带 5 秒超时的 `curl https://github.com` 失败。现有 `/init/proxy/proxy.ini` 由 `frpc` 使用，作用是端口转发，没有发现可供 GitHub 下载使用的本地 HTTP 代理监听端口。

因此暂不启用 GitHub 自动更新。当前仓库中的 Docker 定时同步脚本不能直接用于这台服务器；继续尝试会违反“网络失败时只报告、不强行更新”的要求。

后续需要二选一：

1. 为 AutoDL 容器提供可验证的 HTTP/HTTPS 出口代理，然后把直接 Waitress 更新脚本安装为每日 04:00 定时任务；或
2. 使用 GitHub Actions 通过 SSH 将构建好的发布归档推送到服务器，再由服务器本地备份、迁移、重启和健康检查。该方案不要求服务器主动连接 GitHub，但需要配置专用 SSH 部署密钥。

## 后续底图配置更新

完成上述只读核查后，已按用户要求从本机运行实例复制 Mapbox 与天地图 Token。写入前备份了服务器 `app.toml`，随后重启原有 6007 服务；健康检查正常，应用端口和公网转发的 `/api/bootstrap/` 均确认两个 Token 已配置。两端临时令牌文件已删除，实际 Token 未写入 GitHub。

这次配置更新通过本机 SSH 完成。GitHub 自动部署和每日 04:00 定时更新仍未启用。
