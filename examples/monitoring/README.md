# 遥感监测接入配置

业务路线与科学输入要求见 [遥感监测接入](../../docs/remote-sensing-monitoring.md)。本目录不登记演示数据或自动发布未经验证的模型。

## 只读准备检查

将 `config/monitoring.example.toml` 复制为 `config/monitoring.local.toml`，核对源目录、完整恢复回执与冻结清单。配置集中在 TOML 和脚本顶部，不要求环境变量；直接运行：

```sh
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python tools/monitoring/prepare.py
```

服务器使用现有平台解释器；纯元数据检查不依赖 PyTorch、Zarr 或 scikit-learn。检查仅读取清单、文件大小、小文件摘要和地理头信息，不解码整幅影像、不解压总包、不运行模型。缺少完整恢复回执时 `transferVerified` 为 false；全部文件存在仍不等于模型可执行。`modelExecutable` 保持 false，真实执行通过计算中心的已验证算子版本完成。

服务器配置可独立保存在正式配置目录，用`--config <monitoring.toml绝对路径>`选择，避免程序升级时丢失本机路径。默认不传参数时读取脚本顶部的`CONFIG_PATH`。完整立方体选用`wildfire/seasfire_v0.4.zarr`，不选择缺少坐标块的demo副本。

## 项目与成果登记

超级管理员为已有项目显式配置场景。保留胡杨演示时使用 `source: tarim_poplar_mock` 并增加 `scenes: [spartina, wildfire]`；不增加 scenes 时原演示保持原样。

```sh
cd backend
<平台Python> manage.py project_feature ecology_monitor --project <项目编码> --enable --config <project-config.json绝对路径> --actor <超管用户名>
```

先通过现有矢量/栅格导入将地图成果登记为本项目资源。准备矢量瓦片后，将 `spartina-product.json` 的 `resourceId` 和 `sourceResourceIds` 替换为真实 ID，并填写实际来源、统计与局限；示例 ID 不能直接用于实际登记。

```sh
<平台Python> manage.py prepare_vector_tiles --project-id <项目ID> --resource-id <实际资源ID>
<平台Python> manage.py register_monitor_product --project <项目编码> --actor <超管用户名> --manifest <产品清单绝对路径>
```

产品清单遵循 OpenAPI `MonitoringProductManifest`。相同编码和内容重复执行不会新增产品；不同内容须使用新编码。原始影像、模型权重和 Zarr 不通过这条命令复制。新模型任务的输出仍先经过计算中心质量门禁和标准入库，再交接给大屏。

成果展示→生态监测大屏选择场景和产品，手动刷新可读取新登记成果。没有可见成果时展示待接入状态；删除来源、停用资源或撤销 owner_only 访问后，该产品与统计不再返回。

完整发布可使用`tools/release/release.py full --candidate-check <tools/monitoring/candidate_check.py绝对路径> --execute`。钩子先确认候选数据库、科研目录和配置均隔离，再验证场景接口、鉴权、未知时间与虚假预报拒绝；临时项目设置和会话均在回滚事务内，不登记模拟产品。
