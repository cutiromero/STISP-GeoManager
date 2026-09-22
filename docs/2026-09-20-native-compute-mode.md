# 本机进程计算模式

## 决定

AutoDL 当前实例运行在受限容器内，无法创建 Docker 镜像或启动容器。计算中心增加 `compute.mode = "native"` 后，可以使用服务器已有的 Python 地理环境运行算法包，不再依赖 Docker daemon。Docker 模式继续保留给具备容器权限的部署环境。

本机模式仍使用同一个 `deploy/compute/runner.py` 协议、任务队列、输入快照、输出格式校验、超时、内存/CPU 软限制和任务恢复流程。每次任务在独立子进程中启动，worker 只读取状态文件和声明的输出文件；算法包不会导入 Django 或访问数据库连接。

## 配置

生产配置的 `[compute]` 段使用：

```toml
mode = "native"
interpreter = "/root/autodl-tmp/geomanager-env-20260919/bin/python3.14"
memory_mb = 2048
timeout_seconds = 1800
input_mb = 1024
output_mb = 1024
retention_days = 7
user_queue = 3
global_queue = 20
```

也可以在后端环境中运行 `python manage.py configure_compute_runtime --native --config <生产配置>` 写入该段。启动计算 worker 后，`GET /api/compute/runtime/` 会报告本机 Python、GeoPandas、Rasterio、PyProj 等依赖版本摘要；算法版本绑定这个摘要，环境变化后需要重新试运行。

## 验收

验收需要使用 NDVI 模板完成：登记算法、上传 ZIP、管理员试运行、检查 GeoTIFF 数值和坐标参考系、发布版本、普通用户提交任务、下载结果并入库。任一输入或输出检查失败都不能标记任务成功。

本模式没有 Docker 的文件系统、网络和 capability 隔离能力。它只适合管理员明确接受主机进程执行风险的 AutoDL 实例；需要更强隔离时，应将配置切回 `mode = "docker"` 并提供具备 Docker 权限的 Linux 执行节点。
