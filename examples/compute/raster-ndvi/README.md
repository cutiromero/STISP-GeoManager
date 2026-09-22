# NDVI示例

分类：遥感计算。这是可下载、修改后重新注册的普通算法包，平台业务代码不识别算法名称。

入口为 `main.py` 的 `run(context)`。输入使用 `context.input_path(key)`，参数通过 `context.parameters` 读取，输出写入 `context.output_path(filename)`。只能使用运行环境中已有依赖；运行时没有网络。输出文件名必须符合清单。

将这三个文件直接压缩到 ZIP 根目录，登记同名 identifier 后上传。试运行成功且人工核对数据后，由有发布权限的管理员发布。修改实现或清单需增加 version。
