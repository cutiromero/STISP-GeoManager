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

`monitorConfig`包含标题`title`、显式数据源`source`、研究区`initialView`和可选`scenes`。`tarim_poplar_mock`展示胡杨模拟点位，省略scenes时保持原演示；显式增加`["spartina", "wildfire"]`可切换本项目遥感场景。`remote_sensing_products`仅展示真实遥感产品，省略scenes时启用两场景。其他项目不自动选择数据源，未知源不回退。

```json
{
  "title": "塔里木河流域胡杨林生态监测",
  "source": "tarim_poplar_mock",
  "initialView": { "center": [84, 39.9], "zoom": 2.05, "regionZoom": 5.15 }
}
```

保存为 JSON 后执行 `"$PY" manage.py project_feature ecology_monitor --project <项目编码> --feature-config <配置文件绝对路径> --actor <超管用户名>`；可同时加 `--enable`。配置文件内容为 `null` 时清除配置，单独开关不会删除配置。经纬度、缩放级别、标题和数据源均校验，错误不写入数据或审计。

迁移 `projects.0003_project_features` 只新增两张表和唯一约束，原项目、成员关系及科研数据不改动。已有稳定代码 `05` 的项目按 ID 关联初始化开启和首份配置，不依赖显示名称；不存在该代码时安全跳过，不创建项目。其他项目默认关闭，全局默认关闭。初始化使用 `get_or_create`，不会覆盖之后的设置；测试覆盖真实从旧版本升级、目标缺失与重复初始化。常规升级执行 `manage.py migrate` 后自动生效，无需另行手工开启。

胡杨演示包含流域监测地球、点位详情、区域综合风险、地下水埋深、土壤含水率、NDVI、胡杨长势评分、最近24次观测趋势、倒序预警、高风险区段排行与生态态势研判。页面以“演示数据”标识来源，使用业务名称和简洁状态；未接入报告服务时不显示报告按钮。

遥感场景包含成果列表、真实地图图层、指标、来源、质量与时间依据、适用范围和业务展示路线。互花米草展示分布面、面积和斑块；野火展示区域风险概率或历史观测。未知观测时间保持空值，统计缺失显示“—”，不使用登记时间、权重文件名推断观测日期或预测时效。没有产品时显示待接入状态，不生成模拟读数或结论。

大屏直接呈现监测对象、分布、指标、日期和来源。模型输入维度、软件依赖、平台保护规则等接入细节留在管理文档；统计口径与成果信息按需展开。状态使用“待核验”“日期待补充”“数据接入中”等业务用语，不在主画面重复展示防御性说明。

## 数据源边界

胡杨演示使用`frontend/src/monitor/types.ts`中的`MonitorDataSource`：

- `getSnapshot(): Promise<MonitorSnapshot>`：返回序号、更新时间、点位、关联、预警、历史样本与研判。
- `subscribe(listener): () => void`：订阅 `MonitorEvent`，返回幂等取消函数；最后一个订阅取消后释放数据源持有的计时器和可见性监听。

快照中的点位具有稳定 ID、名称、河段、经纬度、水文/土壤/林分类型、指标读数、风险分值与等级、最近事件和更新时间。单位分别为地下水埋深 `m`、土壤体积含水率 `%`、无量纲 NDVI、演示长势评分 `/100`。风险等级为 `normal`、`attention`、`warning`、`critical`；演示阈值依次为 35、55、75，不能当作业务预警标准。

增量事件携带单调递增 `sequence`、时间、更新后的完整点位、区域均值样本、可选的新预警或预警解除，以及完整研判。ID 均为稳定字符串，时间采用 ISO 8601，坐标顺序为经度、纬度。`assessment.simulated` 明确标识研判是否模拟；当前页面始终标识整页数据为模拟。

`useMonitor.ts` 先订阅再读取快照，读取期间缓冲事件，按序号应用并忽略重复事件。页面保留最近 24 个趋势样本和 40 条预警记录，解除操作保留原预警与解除时间，不重复计入待关注数量。

## 模拟实现与真实数据接入

固定点位、基线和初始预警在 `frontend/src/monitor/mockData.ts`；模拟事件调度在 `frontend/src/monitor/mockSource.ts`。默认种子为 `20261110`，间隔为 4000 ms；工厂选项支持 `seed`、`intervalMs`、`now`、`locale` 与可注入的可见性源。相同种子、时钟和配置可复现事件序列。变化仅演示事件流，不模拟真实生态过程的时间尺度。

`EcologyMonitorPage`按配置和场景装配页面。`frontend/src/monitor/source.ts`只装配显式胡杨模拟源；遥感产品通过`productApi.ts`读取`GET /api/ecology/monitoring/`，使用生成的OpenAPI类型。互花米草与野火不转换为地下水、土壤或胡杨长势点位。

遥感产品复用`RemoteSensingProduct`和已入库`DataResource`。超级管理员用`register_monitor_product`登记产品交接清单，同项目编码和内容重复登记幂等，内容不同须新编码。新模型成果须已经通过计算中心质量门禁与标准入库，并保留任务全部来源；历史外部成果按historical登记。产品和全部来源每次读取重验项目、状态与owner_only权限。场景目录只读元数据，选择产品后使用现有profile与瓦片接口，资源接口再次鉴权；浏览器不读取原始TIFF/Zarr。

页面手动刷新成果，无后台模拟更新或定时重算。切换产品取消旧profile和渲染请求，切换项目/场景释放旧地图并忽略迟到响应；读取权限失败清除旧成果与统计。栅格沿用后端异步渲染和实际瓦片采样规则，矢量使用预生成MVT，尚未准备瓦片时明确提示。完整数据、模型、业务路线与接入命令见[remote-sensing-monitoring.md](remote-sensing-monitoring.md)及`examples/monitoring/`。

## 地图与动态效果

胡杨、互花米草和野火使用同一套`MonitorDashboardFrame`、`MonitorPanel`和`useMonitorMap`。主画面固定为左侧地球、右侧六张业务卡片，标题栏、时钟、动效、全屏和地图控件保持一致；领域差异体现在指标、成果和研判内容。资料列表归入右侧卡片，不另设整屏侧栏或独立的布局样式。

桌面卡片行高随可用窗口高度分配，研判行保留正文高度；长文本、排行榜与列表在各自内容区滚动。低高度窗口允许信息区整体滚动，窄屏改为页面纵向排列；底栏参与正常布局。点位详情和地图提示限制在地图可视范围内。全屏进退、窗口缩放及等值配置刷新保留地图实例与当前视角，手动刷新保留仍可访问的选中成果。

地图直接使用现有 `createBasemapStyle`、平台 `bootstrap.map` 令牌与底图选择、`projectTransformRequest`，不新增地图服务。采用 Mapbox GL JS `globe` 投影，全球视角按容器尺寸自适应展示完整地球；研究区视角采用配置的 `regionZoom`，保留来源署名。头部以单行标题、时钟和操作按钮展示，副标题及完整日期、观测更新时间通过悬停说明读取。整页共用带缓慢位移和独立星光明暗变化的星空，左侧无卡片边框，右侧信息卡片透明。地球使用真实地表与地图原生大气渲染，大气光晕随视角及缩放变化。全球视角保留紧凑点位、上下游关联线及位于研究区的点位数量标记，点击标记可进入研究区；缩放切换只控制底图标签，不隐藏监测数据。研究区判定相对于完整地球的拟合缩放级别，避免大屏窗口中的完整地球被误判为局部视角。点位中心色表示监测类型，外环色表示风险；弧线为上下游关联示意，不是河道几何。点位位于塔里木河干流及主要支流的真实地理范围内，但不对应实测站址。

鼠标进入地球的圆形范围时暂停自转，移开后恢复；背景继续运动。实际地图拖动、缩放、键盘交互后暂停自转约 1.8 秒，地图外点击不延长暂停，研究区放大视角不自转。页面提供启动、暂停动效按钮。预警按新到旧排列，列表内容平滑向上移动，鼠标悬停或键盘聚焦时暂停。默认遵循系统减少动态效果设置，用户可明确启动演示动效。页面隐藏时停止模拟计时和动画，恢复后继续，不补发隐藏期间的模拟事件。离开页面取消订阅并释放地图、点位与研究区标记、动画帧、时钟和监听器。

## 验证入口

地球画布延伸至底部状态栏上方。“全球视角”和“聚焦研究区”以两个图标按钮竖排在画布右上角，悬停时显示文字说明。地图点位、监测区数量标记及右侧排行均可进入对应的空间数据或详情。

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
