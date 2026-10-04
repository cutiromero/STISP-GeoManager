# 知识服务部署与恢复

主平台继续负责登录、项目和资料权限。WeKnora 与向量服务只监听本机回环地址，由主平台后端调用。服务数据独立于代码目录，密钥保存在服务账号可读的配置文件中。

## 固定版本

- WeKnora：官方 `Tencent/WeKnora` 的 `v0.8.2`，提交 `3e8b0bfc80b845b2d4b2ed683994748741450a97`。官方源码归档 SHA256 为 `54d68abfb2e25678072e82ca49946e2397f686b07ffc09031473bae8535af113`。当前使用 Lite 模式及 SQLite，不依赖 Neo4j。
- 向量模型：官方 `BAAI/bge-m3`，Hugging Face 提交 `5617a9f61b028005a4858fdac845db406aefb181`，1024 维。权重文件为 `pytorch_model.bin`，SHA256 为 `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`。
- 模型可从对应的 ModelScope 镜像固定文件版本取得，但必须对照上述官方提交校验：大文件检查官方 LFS SHA256，小文件检查 Git blob SHA1；下载回执保存每个文件的来源版本、大小和哈希。当前仅使用稠密向量，未启用 BGE-M3 的稀疏或 ColBERT 输出。

## 向量服务启动和停止

下列路径均为部署占位符：`<CODE_ROOT>` 为代码目录，`<KNOWLEDGE_ROOT>` 为知识服务运行目录，`<LLM_PYTHON>` 为已安装 torch、transformers、FastAPI 和 uvicorn 的既有 Python。保持其依赖版本不变。

运行目录应包含与发布代码一致的 `embedding_server.py`、模型目录，以及权限为 `600` 的 `embedding.env`。环境文件包含 `KNOWLEDGE_EMBEDDING_API_KEY`、`KNOWLEDGE_EMBEDDING_MODEL_PATH` 和 `CUDA_VISIBLE_DEVICES=4`；真实值由服务器私有配置提供。服务使用 `127.0.0.1:19010`，密钥不进入代码仓库和启动命令行。

```sh
"<MANAGEMENT_PYTHON>" "<CODE_ROOT>/deploy/knowledge/ensure_embedding.py" \
  --root "<KNOWLEDGE_ROOT>" --python "<LLM_PYTHON>"
```

该入口核对 PID 的可执行文件、完整启动参数、工作目录、GPU 配置、当前密钥，以及监听 socket 的所属 PID；随后检查模型就绪和接口鉴权。已就绪时返回相同 PID，未运行时启动后台进程并写入 `embedding.pid`。若端口或记录的 PID 属于其他服务，返回错误并保留原进程。日志写入 `embedding.log`，状态输出只包含安全 JSON。主应用启动入口调用此命令后，再启动依赖知识服务的应用进程。

维护或密钥轮换时，先在旧配置仍有效的情况下精确停止此服务：

```sh
"<MANAGEMENT_PYTHON>" "<CODE_ROOT>/deploy/knowledge/ensure_embedding.py" \
  --root "<KNOWLEDGE_ROOT>" --python "<LLM_PYTHON>" --stop
```

停止操作只向身份匹配的 PID 发送 SIGTERM，等待退出；不会查找并批量终止 Python、GPU、vLLM 或其他服务进程。更新代码或密钥后再次执行启动命令。入口本身不注册开机任务；由已采用的主应用启动机制调用。

## 备份范围与恢复顺序

一次可恢复备份需要共同保留：

1. 主平台业务 SQLite 数据库，包括知识资料、知识域及 WeKnora 对象 ID 的本地映射；同时保留资料附件和主平台配置。
2. WeKnora 的 SQLite 数据库、配置和 `files` 本地文件存储。数据库应使用 SQLite 在线备份或在受控停写后复制；不能只复制正在写入的 `.db` 并遗漏 WAL。
3. 私有环境文件和加密相关密钥，以受限权限加密保存；代码版本、模型下载回执与文件校验清单。模型大文件可单独保存，或按固定版本与哈希重新下载。

备份前暂停资料新增、删除、重新解析和 Wiki 生成，等待正在处理的作业结束，再取得同一停写窗口的主平台及 WeKnora 快照。数据库中的对象 ID、密钥和文件目录应来自同一备份批次。

恢复时先准备对应代码、既有运行环境与模型校验通过的文件；再恢复私有配置、WeKnora 数据库和文件目录；随后恢复主平台数据库及本地映射。先启动向量服务并验证 1024 维输出，再启动 WeKnora，最后启动主平台及其工作进程。检查项目/个人资料隔离、带出处检索、Wiki 来源链接和解析队列后恢复写入。候选测试数据库与测试资料保持独立，不覆盖生产数据。

## 本轮验证范围

2026-10-04 的服务器向量微测验证了鉴权、1024 维归一化向量和三个中文改写问题的预期资料匹配。该微测反映向量接口可用性；完整检索及智能体效率以独立的候选端到端验收回执为准。
