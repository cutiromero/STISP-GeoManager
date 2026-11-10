import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.compute.packages import IDENTIFIER

DEFAULT_VERSION = "0.1.0"


class Command(BaseCommand):
    help = "在当前目录生成可直接自检的第2版算子骨架"

    def add_arguments(self, parser):
        parser.add_argument("identifier")
        parser.add_argument("--directory", type=Path, default=Path.cwd())

    def handle(self, *args, **options):
        identifier = options["identifier"]
        if not IDENTIFIER.fullmatch(identifier):
            raise CommandError("标识须为小写英文、数字、连字符或下划线")
        target = options["directory"] / identifier
        if target.exists():
            raise CommandError("目标目录已存在，拒绝覆盖：" + str(target))
        manifest = {
            "schemaVersion": 2,
            "identifier": identifier,
            "name": "表格复制示例",
            "version": DEFAULT_VERSION,
            "description": "复制小表格，演示字段映射和结构化错误；替换为实际算法后重新自检。",
            "author": "待填写",
            "runtime": "python-geospatial-v1",
            "agent": {"enabled": False},
            "capabilities": {
                "operations": ["convert"],
                "dataTypes": ["table"],
                "summary": "保留字段的表格复制",
                "useWhen": "需要验证算子制作流程",
                "avoidWhen": "需要科学推断或坐标转换",
            },
            "inputs": [
                {
                    "key": "source",
                    "label": "来源表格",
                    "kind": "table",
                    "description": "含一个名称字段的小表格",
                    "fields": [
                        {
                            "role": "name",
                            "description": "对象名称",
                            "types": ["string"],
                            "required": True,
                        }
                    ],
                    "crs": {"mode": "any"},
                }
            ],
            "parameters": [],
            "outputs": [
                {
                    "key": "result",
                    "label": "复制结果",
                    "kind": "table",
                    "file": "result.csv",
                    "description": "与来源同字段的副本",
                    "fields": [
                        {
                            "role": "name",
                            "description": "来源对象名称，实际字段名保持映射值",
                            "types": ["string"],
                            "required": True,
                        }
                    ],
                    "final": True,
                }
            ],
            "errors": [
                {
                    "code": "MISSING_NAME",
                    "meaning": "对象名称角色未映射",
                    "remedy": "complete_mapping",
                    "precondition": "source须绑定name角色",
                }
            ],
            "resources": {
                "duration": "seconds",
                "memory": "small",
                "scaling": "耗时随输入字节数线性增加；流式复制，额外内存为常数量级。",
            },
            "selfTests": [
                {
                    "name": "单行表格复制",
                    "fixture": "selftest/smoke.json",
                    "expect": {
                        "files": {"result.csv": {"rows": 1, "columns": ["title"]}}
                    },
                }
            ],
            "timeoutSeconds": 60,
            "deterministic": True,
        }
        entry = '''"""将此处替换为实际计算；平台已预检，算子仍须防御性检查。"""
import shutil

from operator_sdk import fail, field_mapping, repeated_inputs

# ==================== 配置 ====================
OUTPUT_FILE = "result.csv"
# 集合输入声明repeat后，可用repeated_inputs(context, "sources")读取。
# =============================================


def run(context):
    mapping = field_mapping(context, "source")
    if "name" not in mapping:
        fail(context, "MISSING_NAME", "请补充对象名称映射", remedy="complete_mapping", inputs=["source"])
    shutil.copyfile(context.input_path("source"), context.output_path(OUTPUT_FILE))
'''
        fixture = {
            "inputs": {"source": {"kind": "table", "rows": [{"title": "样例对象"}]}},
            "parameters": {},
            "fieldMappings": {"source": {"name": "title"}},
        }
        target.mkdir(parents=True)
        (target / "selftest").mkdir()
        (target / "operator.yaml").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (target / "main.py").write_text(entry, encoding="utf-8")
        (target / "selftest/smoke.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (target / "README.md").write_text(
            "# "
            + identifier
            + "\n\n入口：main.py:run(context)。先补充实际语义、错误码与小样例，再启用agent.enabled。\n\n自检：python manage.py check_operator "
            + str(target)
            + "\n",
            encoding="utf-8",
        )
        self.stdout.write("已生成：" + str(target))
