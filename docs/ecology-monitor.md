# 项目生态监测大屏

## 入口与展示范围

成果展示页仅在后端当前项目的 `enabledFeatures` 包含 `ecology_monitor` 时显示入口。独立路由 `/results/ecology-monitor` 沿用登录门禁，未开启时显示“当前项目尚未开启监测大屏”和返回成果按钮。已开启但无本项目内容配置时显示“尚未配置监测内容”，不创建地图或模拟源，不沿用塔大胡杨数据。切换项目后重新装配当前项目配置并清理旧订阅。页面不加载工作台标签页、图层管理或编辑工具。

## 项目功能管理

项目功能使用数据库 `ProjectFeature` 注册表与 `ProjectFeatureSetting` 项目设置。有效开启条件为项目启用且“全局开启或单项目开启”；全局关闭恢复各项目原设置，不清空配置。开关不替代账号权限与项目 ACL，不会让用户看见未授权项目。现有账号 `FeaturePermission` 保持原职责，`GEOLOGY_PROJECT_CODES` 等旧业务常量不扩散到大屏。

超级管理员在后台“项目标签管理”的“项目功能”列开启/关闭，也可在“项目功能全局开关”对全部项目开启。全局开启时单项目开关禁用；先关闭全局开关再维护项目差异。内容配置使用管理命令或设置接口维护。每次设置沿用 `OperationLog`，与数据更新同事务；命令必须指定启用的现有超管账号，不可用普通账号代操作。

在仓库根目录设置解释器，然后执行相应命令：

```sh
PY=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python
cd backend
"$PY" manage.py project_feature ecology_monitor --project 05 --enable --actor <超管用户名>
"$PY" manage.py project_feature ecology_monitor --project 05 --disable --actor <超管用户名>
"$PY" manage.py project_feature ecology_monitor --all-projects --enable --actor <超管用户名>
"$PY" manage.py project_feature ecology_monitor --all-projects --disable --actor <超管用户名>
```

新功能先注册任意稳定 slug 标识，再按同样方式开启，无需添加项目白名单或更改管理页：

```sh
"$PY" manage.py project_feature <功能标识> --register --actor <超管用户名>
"$PY" manage.py project_feature <功能标识> --project <项目编码> --enable --actor <超管用户名>
```

注册默认关闭；业务界面使用后端 `enabledFeatures`，业务接口仍独立执行权限与项目功能校验。已有页面在项目清单刷新后生效，后台保存会立即刷新；其他浏览器重新聚焦、会话恢复或刷新页面时更新。没有新增轮询或独立前端开关缓存。

## 项目内容配置与迁移

`monitorConfig` 包含标题 `title`、显式数据源 `source` 和研究区 `initialView`。目前仅有 `tarim_poplar_mock` 演示源；其他项目不会自动选用它。需要演示时须明确为目标项目保存配置，接入新的数据源时扩展契约和装配器，不允许未知源回退。

```json
{
  "title": "塔里木河流域胡杨林生态监测",
  "source": "tarim_poplar_mock",
  "initialView": { "center": [84, 39.9], "zoom": 2.05, "regionZoom": 5.15 }
}
```

保存为 JSON 后执行 `"$PY" manage.py project_feature ecology_monitor --project <项目编码> --config <配置文件绝对路径> --actor <超管用户名>`；可同时加 `--enable`。配置文件内容为 `null` 时清除配置，单独开关不会删除配置。经纬度、缩放级别、标题和数据源均校验，错误不写入数据或审计。

迁移 `projects.0003_project_features` 只新增两张表和唯一约束，原项目、成员关系及科研数据不改动。已有稳定代码 `05` 的项目按 ID 关联初始化开启和首份配置，不依赖显示名称；不存在该代码时安全跳过，不创建项目。其他项目默认关闭，全局默认关闭。初始化使用 `get_or_create`，不会覆盖之后的设置；测试覆盖真实从旧版本升级、目标缺失与重复初始化。常规升级执行 `manage.py migrate` 后自动生效，无需另行手工开启。

大屏包含流域监测地球、点位详情、区域综合风险、地下水埋深、土壤含水率、NDVI、胡杨长势评分、最近 24 次观测趋势、倒序预警、高风险区段排行与模拟智能体研判。报告按钮只显示“功能建设中”。所有点位、读数、风险与研判均为演示，不代表实测，不用于生态决策。

## 数据源边界

`frontend/src/monitor/types.ts` 定义页面唯一依赖的 `MonitorDataSource`：

- `getSnapshot(): Promise<MonitorSnapshot>`：返回序号、更新时间、点位、关联、预警、历史样本与研判。
- `subscribe(listener): () => void`：订阅 `MonitorEvent`，返回幂等取消函数；最后一个订阅取消后释放数据源持有的计时器和可见性监听。

快照中的点位具有稳定 ID、名称、河段、经纬度、水文/土壤/林分类型、指标读数、风险分值与等级、最近事件和更新时间。单位分别为地下水埋深 `m`、土壤体积含水率 `%`、无量纲 NDVI、演示长势评分 `/100`。风险等级为 `normal`、`attention`、`warning`、`critical`；演示阈值依次为 35、55、75，不能当作业务预警标准。

增量事件携带单调递增 `sequence`、时间、更新后的完整点位、区域均值样本、可选的新预警或预警解除，以及完整研判。ID 均为稳定字符串，时间采用 ISO 8601，坐标顺序为经度、纬度。`assessment.simulated` 明确标识研判是否模拟；当前页面始终标识整页数据为模拟。

`useMonitor.ts` 先订阅再读取快照，读取期间缓冲事件，按序号应用并忽略重复事件。页面保留最近 24 个趋势样本和 40 条预警记录，解除操作保留原预警与解除时间，不重复计入待关注数量。

## 模拟实现与真实数据接入

固定点位、基线和初始预警在 `frontend/src/monitor/mockData.ts`；模拟事件调度在 `frontend/src/monitor/mockSource.ts`。默认种子为 `20261110`，间隔为 4000 ms；工厂选项支持 `seed`、`intervalMs`、`now`、`locale` 与可注入的可见性源。相同种子、时钟和配置可复现事件序列。变化仅演示事件流，不模拟真实生态过程的时间尺度。

`frontend/src/monitor/source.ts` 是唯一数据源装配入口，接收当前项目 ID、语言和后端项目配置，仅按显式 `source` 返回 `MonitorDataSource`。真实接入时创建实现同一接口的真实数据源，保留模拟实现用于测试，图表、点位和窗口无需改写。真实数据源负责认证、项目范围、功能开关、错误恢复、序号缺口的重新取快照、断线重连及隐藏期间的传输暂停；前端门禁不代替服务端 ACL。接入完成后同步更新整页模拟标识与连接状态文案，并按契约流程扩展数据源配置。

## 地图与动态效果

地图直接使用现有 `createBasemapStyle`、平台 `bootstrap.map` 令牌与底图选择、`projectTransformRequest`，不新增地图服务。采用 Mapbox GL JS `globe` 投影，全球视角按容器尺寸自适应展示完整地球；研究区视角采用配置的 `regionZoom`，保留来源署名。整页共用缓慢流动的深空背景，左侧无卡片边框，右侧信息卡片透明。地球通过真实地表、自然大气光晕和明暗层次呈现，点位列表与图例按需展开。全球视角收起点位与底图标签，研究区视角显示监测点位及标签。点位中心色表示监测类型，外环色表示风险；弧线为上下游关联示意，不是河道几何。点位位于塔里木河干流及主要支流的真实地理范围内，但不对应实测站址。

鼠标进入地球的圆形范围时暂停自转，移开后恢复；背景继续运动。拖动、缩放、键盘与指针交互后仍暂停自转 15 秒，研究区放大视角不自转。预警按新到旧排列，列表内容平滑向上移动，鼠标悬停或键盘聚焦时暂停。系统开启减少动态效果时，禁用自转、背景动画、脉冲、闪烁、数字滚动与列表自动滚动。页面隐藏时停止模拟计时和动画，恢复后继续，不补发隐藏期间的模拟事件。离开页面取消订阅并释放地图、标记、动画帧、时钟和监听器。

## 验证入口

```sh
make verify-fast
cd frontend
export PATH=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin:$PATH
export COREPACK_ENABLE_NETWORK=0
pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false exec vitest --config vitest.config.ts --configLoader runner --no-cache run src/monitor/mockSource.test.ts
pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false run i18n:check
node scripts/run-browser-check.mjs src/pages/EcologyMonitorPage.browser.test.tsx --configLoader runner
```

浏览器测试使用 Mapbox 构造器与标记替身，覆盖项目入口隔离、整屏窗口、增量更新、点位详情、报告提示、减少动态效果、悬停与键盘暂停、页面可见性、资源释放及四组分辨率的横向溢出检查。真实 WebGL、外部瓦片与令牌有效性需要在浏览器中另行验收。
