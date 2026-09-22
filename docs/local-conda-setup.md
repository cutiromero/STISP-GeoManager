# 本机 Conda 开发环境（2026-09-22）

本机已建立独立环境 `stisp-geomanager`，不修改 `uboo`、base 或其他研究环境。该记录接续 `handoff-2026-09-22.md`，其中“新电脑尚未配置”的描述为本次安装前状态。

## 日常使用

- 双击仓库根目录 `启动本地平台.cmd`，就绪后打开网页。
- 双击 `停止本地平台.cmd`，仅停止本项目启动脚本登记的进程树。
- 浏览器访问 `http://127.0.0.1:5173/`。
- 管理员账号 `admin`；随机初始密码在仓库上一级 `GeoManagerData/appdata/database/initial_superadmin_password.txt`。不要提交密码文件，也不要使用师兄生产账号。
- 重启电脑后重新启动即可；未安装开机自启或服务器同步任务。

也可在项目根目录执行：

```powershell
./start-local.ps1 -NoBrowser
./start-local.ps1 -Mode Stop
```

## 环境与数据位置

| 项目 | 本机值 |
| --- | --- |
| Conda 环境 | `C:/Users/uboo/miniconda3/envs/stisp-geomanager` |
| Python / Django | 3.14.6 / 6.0.6 |
| GDAL / Rasterio / GeoPandas | 3.12.3 / 1.5.0 / 1.1.3 |
| 前端 | pnpm 11.19.0；Node 24 系列，由启动脚本选取可用运行时 |
| 私有本机配置 | `config/app.test.toml`，Git 忽略 |
| 环境指针 | `.runtime/local-environment.json`，Git 忽略 |
| 业务目录 | 仓库上一级 `GeoManagerData/appdata/` |
| 科研目录 | 仓库上一级 `GeoManagerData/research/` |
| 本地日志 | `logs/local-*.log`，Git 忽略；原后端会在启动日志打印初始账号信息，不外传 |

Conda 的 219 个包直接取自 `backend/pixi.lock` 的 win-64 依赖列表，固定 URL 和 MD5 导出至 `backend/conda-win-64.lock`。没有另解一套业务依赖，也没有修改原 Pixi 锁文件。

新电脑可先执行以下命令恢复依赖；环境存在时先检查，不覆盖已有环境：

```powershell
conda create -n stisp-geomanager --file backend/conda-win-64.lock -y
cd frontend
pnpm install --frozen-lockfile
```

然后复制 `config/app.example.toml` 为被忽略的 `config/app.test.toml`，将 debug 设为 true、allowed_hosts 保持 localhost/127.0.0.1、waitress_host 设为 127.0.0.1，业务和科研路径设为本机独立目录。按需要明确选择计算执行器；本机 native 的 interpreter 指向新环境 python.exe。模型仅注册 `mock-local` / `http://127.0.0.1:19100/v1`，不要复制生产密钥。

环境指针内容示例（绝对路径按实际电脑填写）：

```json
{
  "pythonPrefix": "C:/Users/uboo/miniconda3/envs/stisp-geomanager",
  "startMock": true
}
```

修改后台代码或运行命令时，打开新的 PowerShell 窗口，在仓库根目录执行：

```powershell
. ./activate-local.ps1
cd backend
python manage.py check --config ../config/app.test.toml
python manage.py migrate --config ../config/app.test.toml
python -m pytest tests/unit/core/test_cli.py tests/unit/test_compute_runtime.py tests/integration/test_agent.py tests/integration/test_agent_workflow.py -q
```

不要仅依赖 `conda activate`：本机父进程 PATH 含 base 和 uboo 的 GDAL DLL 目录，Rasterio 会遍历这些目录，可能加载错误 DLL。`activate-local.ps1` 只为当前进程排除其他 GDAL 路径并设置本环境 GDAL/PROJ 路径，不修改注册表或系统 PATH。关闭窗口即可结束该进程环境。

## 本次启动内容

- Vite 前端：127.0.0.1:5173。
- Django 开发后端：127.0.0.1:8000。
- 独立 compute_worker、agent_worker、workflow_worker。
- 明确标记的模拟模型：127.0.0.1:19100，随启动/停止脚本一起管理。

计算采用已有 native 模式；已验证可信的仓库表格算法在真实子进程执行。该模式在 Windows 不提供容器隔离及 POSIX 资源硬限制，只用于本机可信算法开发。未安装 WSL/Docker，未发布示例算法，也未连接新疆服务器。

模拟模型可验证聊天和任务链路，但不代表真实模型推理、视觉或深度思考能力。工作流沿用已有无 LangGraph 时的兼容执行路径，已验证仅生成计划；没有自动安装额外编排依赖或开启算子策略。

这是全新本地数据目录，没有复制生产科研数据、底图 Token 或模型配置；空目录和“暂无已发布算法”属于预期。Mapbox/天地图底图需另行配置合法 Token，本次不宣称外部底图服务通过验收。

## 实际验证

- Conda 安装成功；核心地理库导入成功；`pip check` 无冲突。
- Django 系统检查、所有已有数据库迁移和 `makemigrations --check --dry-run` 通过。
- 前端 frozen-lockfile 安装、typecheck、build 通过。
- 后端 CLI、计算运行环境、智能体及工作流共 35 项测试通过。
- Chrome 无头浏览器实际登录成功；数据目录、计算中心、智能体页面加载，相关浏览器流程无未捕获脚本异常。
- Mock 会话被独立 worker 处理成功，科研工作流生成计划成功；计算接口报告运行环境及 worker 在线。
- 真实 native 子进程运行人工表格分组均值：A 组 1、3 → 2；B 组 7 → 7，结果正确。这验证计算依赖和执行链路，不等于完整算法发布/入库验收。
- 重复启动不增加服务进程。启动脚本保留 PID 与启动时间匹配检查。
- 停止后 5173/8000/19100 端口均释放；重新启动通过健康检查，三个 worker 心跳均在 1 秒内。
- 地图工作台和 canvas 已显示，无未捕获脚本异常；外部瓦片请求未在 networkidle 超时内完全结束，不据此判定外部底图全部验收通过。

浏览器 QA 额外安装在本环境的工具：playwright 1.61.0、greenlet 3.5.6、pyee 13.0.1；使用现有 Chrome，不下载浏览器。这三个包不属于应用必需依赖。需要重做同类 QA 时可安装 `playwright==1.61.0 greenlet==3.5.6 pyee==13.0.1`。

安装日志、临时测试脚本和截图位于 `.runtime/setup/`，不纳入 Git。没有修改业务 API、权限规则或栅格渲染算法；仅配置本机数据根目录、依赖与启动方式。
