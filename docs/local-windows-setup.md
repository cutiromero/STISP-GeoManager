# 本机启动说明（2026-09-16）

访问地址：http://127.0.0.1:5173/

在上一级项目目录双击 `启动平台.cmd`，等待服务就绪后浏览器自动打开；双击 `停止平台.cmd` 停止由脚本创建的服务。重启电脑后需重新启动。前后端仅监听本机，端口分别为 5173 和 8000。

管理员用户名为 `admin`。本机新生成的初始密码保存在 `D:/6-时空智能平台开发/GeoManagerData/appdata/database/initial_superadmin_password.txt`。旧运行文档中的历史密码不适用于本机新数据库。

## 本机环境和数据

- 前端使用现有 Node.js 24.19.0、pnpm 11.19.0，已按 pnpm-lock.yaml 安装依赖并构建。
- 后端 Pixi 0.81.0 位于 `.runtime/tools/pixi.exe`；依赖按 backend/pixi.lock 安装，环境位于 backend/.pixi/envs/default，包含 Python 3.14 和 Django 6.0.6 及地理数据组件。
- 启动脚本使用本机已安装的 PowerShell 7 和 Codex 提供的 Node.js/pnpm 路径；若将项目复制到其他电脑，需要重新安装环境并调整启动入口。
- 配置文件：config/app.test.toml。
- 业务数据：D:/6-时空智能平台开发/GeoManagerData/appdata。
- 科研数据：D:/6-时空智能平台开发/GeoManagerData/research。
- 日志：logs/local-Backend.*.log、logs/local-Frontend.*.log。

启动脚本可重复运行；端口已监听时不会重复启动。停止脚本仅停止其记录且启动时间匹配的进程树。

## 已完成验证

- `pnpm install --frozen-lockfile`：成功。
- `pnpm run build`：成功。
- `pixi install --locked`：成功。
- `pixi run python manage.py check --config ../config/app.test.toml`：通过，无问题。
- `pixi run migrate`：所有迁移成功。
- 经前端代理访问 `/api/health/`：status=ok、configLoaded=true。
- 浏览器真实登录：成功进入 `/data`，显示超级管理员、资源目录及初始化分类。
- 重复执行启动脚本：成功，未发生端口冲突。

本次未修改业务代码、API 契约、权限规则或栅格渲染逻辑；只配置了运行环境、数据路径和启动入口。数据目录为空，因此没有导入真实科研资源；真实数据导入和外部地图服务未做验收。前端开发日志有 react-router 预构建提示，未阻止网页加载及登录。
