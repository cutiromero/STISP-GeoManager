# 本机文档检索与自动 Wiki

平台继续负责账号、项目、资料归档和界面；WeKnora 负责文档切分、向量及关键词检索、自动 Wiki。两者通过仅本机可访问的接口连接。资料检索展示原文片段；Wiki 显示为模型整理内容并保留引用来源。

## 固定版本与运行方式

- WeKnora 官方 `v0.8.2`，提交 `3e8b0bfc80b845b2d4b2ed683994748741450a97`。
- 官方源码：`https://github.com/Tencent/WeKnora/archive/refs/tags/v0.8.2.zip`。
- 源码 ZIP SHA256：`54d68abfb2e25678072e82ca49946e2397f686b07ffc09031473bae8535af113`。
- Go 1.26.0 linux-amd64，SHA256：`aac1b08a0fb0c4e0a7c1555beb7b59180b05dfc5a3d62e40e9de90cd42f88235`。
- 本地补丁版本 `v0.8.2-stisp1`：修复官方 Lite 中 Wiki 的 PostgreSQL 专用查询和 SQLite JSON 数组读取问题；保留 PostgreSQL 分支。补丁 SHA256：`632dffed5c9cb542d238d82fc9ea989c6962ca4b86733c2b06b394563803765f`。
- Lite 使用 SQLite、sqlite-vec、FTS5、进程内队列；Wiki 待处理任务保存于数据库并支持重启续跑。此部署使用关系可视化和有来源的 Wiki 页面。
- 上游 Neo4j GraphRAG 和代码沙箱关闭；中文 BGE-M3 向量服务由 `embedding_server.py` 提供，已有 Qwen 接口负责整理文档。

## 构建与初始化

在 Linux 服务机使用现有 Python 和 SQLite 头文件；不修改现有模型服务或安装系统服务。下面路径是本次部署实例，可替换为新的独立目录。

```sh
bash deploy/knowledge/build_weknora.sh \
  /root/autodl-tmp/weknora-0.8.2-20261004 \
  /path/to/weknora-v0.8.2.zip \
  /root/autodl-tmp/geomanager-env-20260919/include
```

构建脚本校验源码、工具链及补丁，应用到独立源码目录，运行 SQLite 仓库回归测试，输出 `WeKnora-lite.new`。审核后在知识服务空闲且已停止时替换 `WeKnora-lite`；不覆盖运行中的二进制。保留原二进制及数据库备份。

```sh
/root/autodl-tmp/geomanager-env-20260919/bin/python3.14 \
  deploy/knowledge/initialize_weknora.py \
  --root /root/autodl-tmp/weknora-0.8.2-20261004 \
  --source /root/autodl-tmp/weknora-0.8.2-20261004/source-stisp1/WeKnora-0.8.2 \
  --embedding-env /root/autodl-tmp/geomanager-knowledge/embedding.env \
  --label production
```

初始化建立独立 tenant、API 密钥及模型登记。密钥置于权限 `0600` 的外部文件；注册完成后关闭开放注册。模型地址是已有本机服务：向量 `19010`、Qwen `19000`。`bridge-config.json` 记录可供平台配置使用的非敏感 ID 与密钥文件路径。

## 运行与平台配置

```sh
/root/autodl-tmp/geomanager-env-20260919/bin/python3.14 \
  deploy/knowledge/ensure_weknora.py \
  --root /root/autodl-tmp/weknora-0.8.2-20261004 --label production
```

生产只监听 `127.0.0.1:19020`，候选只监听 `127.0.0.1:19021`。启动器核对 PID 的可执行文件、工作目录、完整参数及实际监听 socket；端口身份不明时拒绝启动或停止。`--stop` 只向身份匹配的进程发送正常退出信号。

平台配置文件增加以下部署字段，ID 取自该实例 `bridge-config.json`：

```toml
[application.knowledge.weknora]
enabled = true
base_url = "http://127.0.0.1:19020"
api_key_file = "/root/autodl-tmp/weknora-0.8.2-20261004/production/api-key"
tenant_id = 1
embedding_model_id = "实例登记的向量模型 ID"
chat_model_id = "实例登记的语言模型 ID"
timeout_seconds = 20
```

启动平台前先确保向量服务、WeKnora 就绪。平台迁移建立资料映射表；每个项目及私有所有者分别建立上游知识库。平台会在查询之前和返回结果之后核验可见范围。原文件和抽取文本保存在平台资料目录，数据库保存 SHA256；上游上传使用文件内容去重，网络重试不会重复建文档。

## 验证和维护

- 平台回归：`test_weknora_client.py`、`test_knowledge_library.py`、`test_weknora_launcher.py`。
- 上游补丁回归：`go test -tags sqlite_fts5 ./internal/application/repository -run TestLiteWikiSQLiteCompatibility`；覆盖中文标题、英文别名匹配、来源 ID/旧格式、库隔离、通配符及全文查询。
- 生产资料归档、WeKnora SQLite、文件存储、密钥需一起备份。应用回退保留新增资料和源文件。
- 本次 Wiki 去重对单库最近 2,000 条非归档候选进行标题/别名三元组相似度比较；达到此规模后需扩展索引策略。
- Wiki 首次整理是后台工作，文档可检索与 Wiki 完成是两个独立状态。效率测量应在 Wiki 队列空闲时进行，避免与对话共用模型造成干扰。
- 保留上游源码中的 `LICENSE`、`THIRD_PARTY_NOTICES.md` 及 `licenses/`；WeKnora 主项目为 Tencent MIT License，第三方组件以其各自许可证为准。
