# 智能体、栏目素材与团队资料更新

## 用户可见变化

- 模型对话、数据智能体开启深度思考时，显示“思考强度”弹窗滑块：轻量、标准、深入，对应 low、medium、xhigh。默认沿用后台或当前任务预算方案，可恢复默认；后台原有设置保留。
- 删除“回答由本地模型生成，请核对重要信息”。提交问题或重新生成后，对话滚动到新增问题。
- 栏目导航、平台标识、语言切换、数据导入、公众号和项目图标使用提供的 SVG，颜色随当前界面状态变化。
- 团队页补充韩杨、孙淑慧、高澹宁及文档照片；张依涵邮箱按用户最新指示更新。王浩宇已有论文、黄思圻已有研究方向保留。
- 程文妍的补充文档邮箱与龚鑫滔重复，本次保留系统原值 chengwenyan25@mails.ucas.ac.cn，待用户核对。
- 成果页背景改为用户指定的 2026年9月20日 21_23_33 图片。

## 本地数据及素材

本地项目 ID 2 / stisp-algorithm-qa（算法验收（人工样例））无业务对象关联，仅有一条成员关系。备份后通过 Django 删除项目及成员关系，公开项目保留。数据库备份位于仓库外 GeoManagerData/backups/ui-update-20260924-before.db。本次测试不向业务数据库添加独立验收项目或测试资源。

依用户规则，Git 仅纳入代码与文本；新增的 PNG/JPEG 单独保留在本地资源目录。重新部署需随代码带上以下素材：

- frontend/src/assets/portal/results-showcase-20260924.png：来自 260924团队信息/图素材/Codex 图像 2026年9月20日 21_23_33.png。
- frontend/src/assets/team/han-yang.jpeg：成员信息 - 补充.docx 中 word/media/image8.jpeg。
- frontend/src/assets/team/sun-shuhui.jpeg：同文档 image9.jpeg。
- frontend/src/assets/team/gao-danning.jpeg：同文档 image10.jpeg。

接口契约、开发指南、生成类型同步更新。权限、配置数据路径及栅格渲染规则保持原实现。数据库结构新增用户思考强度字段，已完成本地迁移；服务器尚未部署。

## 验证

- 后端模型参数、任务预算和用户强度：30 项通过，包含 HTTP 模型请求捕获。
- 浏览器：智能体、团队、导航、成果四组共 22 项通过。
- TypeScript、OpenAPI 生成一致性、迁移一致性检查通过；OpenAPI 有 6 个已有未使用组件警告。
- 前端 409 项单元测试、Vite 构建、变更文件 lint/格式及品牌检查通过。
- 游客登录实际本地网页检查：11 张成员照片加载成功，栏目图标、平台彩色标识及成果背景显示正常。截图保存在本地 `.runtime/ui-new-members.png`、`.runtime/ui-results.png`。

本地服务地址：http://127.0.0.1:5173/。Python 文档与数据库只读工具使用 uboo；Django 检查和运行使用仓库已配置的 stisp-geomanager 环境，未安装或修改环境。自动化测试使用独立测试数据库及 HTTP 模拟模型；没有把测试会话写入业务库。
