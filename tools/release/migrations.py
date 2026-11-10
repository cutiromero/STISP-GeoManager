"""不导入迁移代码的保守 AST 白名单分类器。"""

import ast
import hashlib
from pathlib import PurePosixPath
import re

FIELD_TYPES = {
    "AutoField",
    "BigAutoField",
    "SmallAutoField",
    "BigIntegerField",
    "IntegerField",
    "SmallIntegerField",
    "PositiveIntegerField",
    "PositiveBigIntegerField",
    "PositiveSmallIntegerField",
    "BooleanField",
    "CharField",
    "TextField",
    "SlugField",
    "EmailField",
    "URLField",
    "GenericIPAddressField",
    "UUIDField",
    "JSONField",
    "DateField",
    "DateTimeField",
    "TimeField",
    "DurationField",
    "DecimalField",
    "FloatField",
    "BinaryField",
    "FileField",
    "ImageField",
    "ForeignKey",
    "OneToOneField",
}
IMPORTS = {
    "from django.db import migrations, models",
    "from django.db import models, migrations",
    "from django.conf import settings",
    "import django.db.models.deletion",
    "import uuid",
}


def symbol(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return symbol(node.value) + "." + node.attr
    return ""


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        raise ValueError("需要静态字面量") from None


def keywords(call):
    if call.args or any(item.arg is None for item in call.keywords):
        raise ValueError("操作仅接受显式关键字参数")
    result = {item.arg: item.value for item in call.keywords}
    if len(result) != len(call.keywords):
        raise ValueError("重复关键字")
    return result


def safe_value(node):
    try:
        literal(node)
        return
    except ValueError:
        pass
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for item in node.elts:
            safe_value(item)
        return
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            safe_value(key)
            safe_value(value)
        return
    if symbol(node) in {
        "dict",
        "list",
        "tuple",
        "uuid.uuid4",
        "settings.AUTH_USER_MODEL",
        "django.db.models.deletion.CASCADE",
        "django.db.models.deletion.PROTECT",
        "django.db.models.deletion.SET_NULL",
        "django.db.models.deletion.RESTRICT",
        "models.CASCADE",
        "models.PROTECT",
        "models.SET_NULL",
        "models.RESTRICT",
    }:
        return
    if isinstance(node, ast.Call) and symbol(node.func) in {
        *("models." + name for name in FIELD_TYPES),
        "models.Index",
        "models.UniqueConstraint",
        "models.Value",
        "models.CheckConstraint",
        "models.Q",
    }:
        for item in node.args:
            safe_value(item)
        for item in node.keywords:
            if item.arg is None:
                raise ValueError("不能展开动态参数")
            safe_value(item.value)
        return
    raise ValueError("存在无法静态证明安全的表达式：" + ast.unparse(node))


def data_python(function, new_models):
    if function.decorator_list or ast.unparse(function.args) != "apps, schema_editor":
        raise ValueError("RunPython 函数签名或装饰器不在白名单")
    variables = {"apps": ("apps", None), "schema_editor": ("editor", None)}

    def expression(node):
        if isinstance(node, ast.Constant):
            return ("value", None)
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                expression(key)
                expression(value)
            return ("value", None)
        if isinstance(node, (ast.List, ast.Tuple)):
            for item in node.elts:
                expression(item)
            return ("value", None)
        if symbol(node) == "schema_editor.connection.alias":
            return ("alias", None)
        if isinstance(node, ast.Attribute):
            kind, model = expression(node.value)
            if node.attr == "objects" and kind == "model":
                return ("query", model)
            if node.attr == "pk" and kind == "row":
                return ("value", None)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if any(item.arg is None for item in node.keywords):
                raise ValueError("RunPython 动态参数")
            if symbol(node.func) == "apps.get_model":
                if len(node.args) != 2 or node.keywords:
                    raise ValueError("get_model 必须显式给出 app 和 model")
                return (
                    "model",
                    tuple(str(literal(item)).lower() for item in node.args),
                )
            kind, model = expression(node.func.value)
            for item in [*node.args, *(item.value for item in node.keywords)]:
                expression(item)
            method = node.func.attr
            if kind == "query" and method == "using":
                if (
                    len(node.args) != 1
                    or node.keywords
                    or not (
                        expression(node.args[0])[0] == "alias"
                        or isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "default"
                    )
                ):
                    raise ValueError(
                        "RunPython using 必须使用迁移连接 alias 或 default"
                    )
                return ("query", model)
            if kind == "query" and method in {"filter", "all"}:
                return ("query", model)
            if kind == "query" and method == "first":
                return ("row", model)
            if kind == "query" and method in {
                "create",
                "get_or_create",
                "update",
            }:
                if model not in new_models:
                    raise ValueError("RunPython 写入基线表或非本迁移新建表")
                return ("pair" if method == "get_or_create" else "row", model)
            if kind == "query" and method == "delete":
                raise ValueError("RunPython delete 的级联写入范围无法静态确认")
        raise ValueError("RunPython 表达式无法静态判断：" + ast.unparse(node))

    def statements(body):
        for statement in body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                kind, model = expression(statement.value)
                target = statement.targets[0]
                if any(
                    isinstance(item, ast.Name) and item.id in {"apps", "schema_editor"}
                    for item in ast.walk(target)
                ):
                    raise ValueError("RunPython 不允许重绑定 apps/schema_editor")
                if isinstance(target, ast.Name):
                    variables[target.id] = (kind, model)
                elif (
                    isinstance(target, ast.Tuple)
                    and kind == "pair"
                    and len(target.elts) == 2
                    and all(isinstance(item, ast.Name) for item in target.elts)
                ):
                    variables[target.elts[0].id] = ("row", model)
                    variables[target.elts[1].id] = ("value", None)
                else:
                    raise ValueError("RunPython 赋值目标无法判断")
            elif isinstance(statement, ast.Expr):
                expression(statement.value)
            elif (
                isinstance(statement, ast.If)
                and isinstance(statement.test, ast.Compare)
                and len(statement.test.ops) == 1
                and isinstance(statement.test.ops[0], (ast.Is, ast.IsNot))
                and len(statement.test.comparators) == 1
                and literal(statement.test.comparators[0]) is None
            ):
                expression(statement.test.left)
                before = dict(variables)
                statements(statement.body)
                variables.clear()
                variables.update(before)
                statements(statement.orelse)
                variables.clear()
                variables.update(before)
            elif isinstance(statement, ast.Pass):
                continue
            else:
                raise ValueError(
                    "RunPython 语句不在白名单：" + type(statement).__name__
                )

    statements(function.body)


def data_sql(node, new_tables):
    sql = literal(node)
    if sql in ("", None):
        return
    if not isinstance(sql, str):
        raise ValueError("RunSQL 仅支持单条字面量 INSERT VALUES")
    match = re.fullmatch(
        r'\s*INSERT\s+INTO\s+["`]?([a-zA-Z_]\w*)["`]?\s*\(\s*[\w"`,\s]+\)\s+VALUES\s*\((.*)\)\s*;?\s*',
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not match or match[1].lower() not in new_tables:
        raise ValueError("RunSQL 不是向本迁移新表写入的简单 INSERT VALUES")
    values = r"(?:NULL|TRUE|FALSE|[-+]?\d+(?:\.\d+)?|'(?:[^']|'')*')"
    if not re.fullmatch(
        rf"\s*{values}(?:\s*,\s*{values})*\s*", match[2], re.IGNORECASE
    ):
        raise ValueError("RunSQL 含表达式、子查询或无法判定的 SQL")


def classify_file(name, source, existing_tables=()):
    operations, affected, new_models, new_tables = [], [], set(), set()
    app = PurePosixPath(name).parts[-3]
    try:
        if not re.fullmatch(r"backend/apps/[^/]+/migrations/[^/]+\.py", name):
            raise ValueError("无法静态确认迁移路径对应的 Django app")
        tree = ast.parse(source, filename=name)
        functions = {}
        migration = None
        for node in tree.body:
            if (
                isinstance(node, (ast.Import, ast.ImportFrom))
                and ast.unparse(node) in IMPORTS
            ):
                continue
            if isinstance(node, ast.FunctionDef) and node.name not in functions:
                if (
                    node.decorator_list
                    or node.returns is not None
                    or node.type_params
                    or ast.unparse(node.args) != "apps, schema_editor"
                ):
                    raise ValueError(
                        "模块函数必须为无装饰器、无默认参数的标准数据迁移函数"
                    )
                functions[node.name] = node
                continue
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "Migration"
                and migration is None
                and not node.decorator_list
                and not node.keywords
                and [symbol(item) for item in node.bases] == ["migrations.Migration"]
            ):
                migration = node
                continue
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            raise ValueError("模块含动态或未知顶层语句")
        if migration is None:
            if PurePosixPath(name).name == "__init__.py" and not functions:
                return {"file": name, "allowed": True, "operations": []}, []
            raise ValueError("缺少标准 Migration 类")
        attrs = {}
        for node in migration.body:
            if (
                not isinstance(node, ast.Assign)
                or len(node.targets) != 1
                or not isinstance(node.targets[0], ast.Name)
            ):
                raise ValueError("Migration 类含动态语句")
            key = node.targets[0].id
            if (
                key not in {"dependencies", "operations", "initial", "atomic"}
                or key in attrs
            ):
                raise ValueError("不支持的 Migration 属性：" + key)
            attrs[key] = node.value
            if key != "operations":
                literal(node.value)
        if not isinstance(attrs.get("operations"), (ast.List, ast.Tuple)):
            raise ValueError("operations 必须为静态列表")
        for operation in attrs["operations"].elts:
            operation_name = (
                symbol(operation.func)
                if isinstance(operation, ast.Call)
                else "未知操作"
            )
            reason = "允许新增且保留旧代码读写能力"
            allowed = True
            try:
                if not isinstance(operation, ast.Call):
                    raise ValueError("操作不是静态调用")
                if operation_name == "migrations.RunPython":
                    if len(operation.args) not in (1, 2) or operation.keywords:
                        raise ValueError("RunPython 仅接受函数及可选 noop 逆操作")
                    if (
                        len(operation.args) == 2
                        and symbol(operation.args[1]) != "migrations.RunPython.noop"
                    ):
                        raise ValueError("RunPython 逆操作无法判断")
                    if symbol(operation.args[0]) != "migrations.RunPython.noop":
                        function = functions.get(symbol(operation.args[0]))
                        if function is None:
                            raise ValueError("RunPython 函数不在本文件")
                        data_python(function, new_models)
                elif operation_name == "migrations.RunSQL":
                    if (
                        not operation.args
                        or len(operation.args) > 2
                        or operation.keywords
                    ):
                        raise ValueError("RunSQL 仅接受静态 SQL 和可选空逆操作")
                    data_sql(operation.args[0], new_tables)
                    if len(operation.args) == 2 and literal(operation.args[1]) != "":
                        raise ValueError("RunSQL 逆操作必须为空")
                else:
                    args = keywords(operation)
                    if operation_name == "migrations.CreateModel":
                        if set(args) - {"name", "fields", "options"}:
                            raise ValueError(
                                "CreateModel 自定义 bases/managers 等无法判断"
                            )
                        model = str(literal(args["name"])).lower()
                        if (app, model) in new_models:
                            raise ValueError("重复新建模型")
                        safe_value(args["fields"])
                        options = args.get("options", ast.Dict(keys=[], values=[]))
                        safe_value(options)
                        if not isinstance(options, ast.Dict):
                            raise ValueError("模型选项必须为字典")
                        option_map = {
                            literal(key): value
                            for key, value in zip(options.keys, options.values)
                        }
                        if set(option_map) - {
                            "db_table",
                            "ordering",
                            "constraints",
                            "indexes",
                            "unique_together",
                            "verbose_name",
                            "verbose_name_plural",
                            "permissions",
                            "default_permissions",
                        }:
                            raise ValueError("未知模型选项或非实体模型")
                        table = (
                            literal(option_map["db_table"])
                            if "db_table" in option_map
                            else app + "_" + model
                        )
                        if not isinstance(table, str) or not re.fullmatch(
                            r"[a-zA-Z_]\w*", table
                        ):
                            raise ValueError("新表名称无法判断")
                        if table.lower() in set(existing_tables) | new_tables:
                            raise ValueError("新表名称与已有表或本迁移新表冲突")
                        new_models.add((app, model))
                        new_tables.add(table.lower())
                    elif operation_name == "migrations.AddField":
                        if set(args) - {
                            "model_name",
                            "name",
                            "field",
                            "preserve_default",
                        }:
                            raise ValueError("AddField 含未知参数")
                        field = args["field"]
                        safe_value(field)
                        if not isinstance(field, ast.Call) or symbol(
                            field.func
                        ) not in {"models." + item for item in FIELD_TYPES}:
                            raise ValueError("不是受支持的标准字段")
                        field_args = {item.arg: item.value for item in field.keywords}
                        model = str(literal(args["model_name"])).lower()
                        if (app, model) not in new_models:
                            if (
                                any(
                                    literal(field_args[key]) is True
                                    for key in ("unique", "primary_key")
                                    if key in field_args
                                )
                                or symbol(field.func) == "models.OneToOneField"
                            ):
                                raise ValueError("不能给已有表增加唯一/主键约束")
                            nullable = (
                                "null" in field_args
                                and literal(field_args["null"]) is True
                            )
                            if not nullable:
                                default = field_args.get("db_default")
                                if (
                                    isinstance(default, ast.Call)
                                    and symbol(default.func) == "models.Value"
                                    and len(default.args) == 1
                                    and not default.keywords
                                ):
                                    default = default.args[0]
                                if default is None or literal(default) is None:
                                    raise ValueError(
                                        "已有表新增非空列必须有非空数据库默认值；Python default 不足"
                                    )
                            affected.append(
                                {
                                    "app": app,
                                    "model": model,
                                    "field": literal(args["name"]),
                                }
                            )
                    elif operation_name in {
                        "migrations.AddIndex",
                        "migrations.AddConstraint",
                    }:
                        if (
                            app,
                            str(literal(args["model_name"])).lower(),
                        ) not in new_models:
                            raise ValueError("索引与约束只允许加在本迁移新建的表上")
                        for value in args.values():
                            safe_value(value)
                    else:
                        raise ValueError("拒绝删除、重命名、修改已有列及任何未知操作")
            except (ValueError, KeyError, TypeError) as error:
                allowed, reason = False, str(error)
            operations.append(
                {
                    "operation": operation_name,
                    "line": operation.lineno,
                    "allowed": allowed,
                    "reason": reason,
                }
            )
    except (SyntaxError, ValueError, TypeError) as error:
        operations.append(
            {
                "operation": "Migration",
                "line": getattr(error, "lineno", 1),
                "allowed": False,
                "reason": str(error),
            }
        )
    return {
        "file": name,
        "allowed": all(item["allowed"] for item in operations),
        "operations": operations,
    }, affected


def classify(baseline, current, read):
    reports, affected = [], []
    existing_tables = set()
    added_names = current.keys() - baseline.keys()
    for name in baseline if added_names else ():
        if current.get(name) != baseline[name]:
            continue
        source = read(name)
        if hashlib.sha256(source).hexdigest() != baseline[name]:
            raise ValueError("基线迁移源码与冻结摘要不符：" + name)
        try:
            for node in ast.walk(ast.parse(source)):
                if (
                    isinstance(node, ast.Call)
                    and symbol(node.func) == "migrations.CreateModel"
                ):
                    args = keywords(node)
                    table = (
                        PurePosixPath(name).parts[-3]
                        + "_"
                        + literal(args["name"]).lower()
                    )
                    options = args.get("options")
                    if isinstance(options, ast.Dict):
                        for key, value in zip(options.keys, options.values):
                            if literal(key) == "db_table":
                                table = literal(value)
                    existing_tables.add(table.lower())
        except (SyntaxError, ValueError, TypeError, KeyError, AttributeError):
            reports.append(
                {
                    "file": name,
                    "allowed": False,
                    "operations": [
                        {
                            "operation": "历史模型身份",
                            "allowed": False,
                            "reason": "不能静态确认基线表名",
                            "line": 1,
                        }
                    ],
                }
            )
    for name in sorted(baseline):
        if current.get(name) != baseline[name]:
            reports.append(
                {
                    "file": name,
                    "allowed": False,
                    "operations": [
                        {
                            "operation": "历史迁移",
                            "allowed": False,
                            "reason": "基线迁移被修改或删除",
                            "line": 1,
                        }
                    ],
                }
            )
    added = {name: current[name] for name in sorted(added_names)}
    for name, expected in added.items():
        source = read(name)
        if hashlib.sha256(source).hexdigest() != expected:
            raise ValueError("迁移源码与冻结摘要不符：" + name)
        report, models = classify_file(name, source, existing_tables)
        reports.append(report)
        affected.extend(models)
    return {
        "schema": 1,
        "baselineMigrations": baseline,
        "addedMigrations": added,
        "allowed": all(item["allowed"] for item in reports),
        "files": reports,
        "affectedModels": affected,
    }


def rejection(result):
    return (
        "；".join(
            f"{report['file']}:{item['line']} {item['operation']}：{item['reason']}"
            for report in result["files"]
            for item in report["operations"]
            if not item["allowed"]
        )
        + "；需要人工制定迁移方案"
    )
