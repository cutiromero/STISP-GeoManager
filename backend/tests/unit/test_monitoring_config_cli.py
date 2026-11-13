from pathlib import Path

from apps.core.config import persist_config_argument
from apps.projects.management.commands.project_feature import Command


def test_feature_json_argument_does_not_replace_runtime_toml(tmp_path):
    runtime = tmp_path / "app.toml"
    content = tmp_path / "monitoring.json"
    runtime.write_text("[application]\n")
    content.write_text("{}")
    args = [
        "manage.py",
        "--config",
        str(runtime),
        "project_feature",
        "ecology_monitor",
        "--project",
        "06",
        "--actor",
        "admin",
        "--feature-config",
        str(content),
    ]
    persist_config_argument(args, tmp_path)
    assert (tmp_path / ".runtime/config-path").read_text().strip() == str(runtime)
    options = (
        Command().create_parser("manage.py", "project_feature").parse_args(args[2:])
    )
    assert options.config == Path(content)
