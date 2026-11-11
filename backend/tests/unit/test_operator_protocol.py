import copy
import io
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import zipfile

from django.core.management import call_command
import numpy as np
import pytest
import rasterio
import yaml

from apps.compute import runtime
from apps.compute import operator_checks
from apps.compute.failures import reported_failure
from apps.compute.operator_checks import check_package, source_packages
from apps.compute.packages import ComputeError, inspect_package, validate_manifest
from apps.compute.preflight import expand_bindings, semantic_preflight
from tests.unit.test_compute_runtime import native_config

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def skeleton(tmp_path):
    call_command(
        "new_operator", "protocol-test", directory=tmp_path, stdout=io.StringIO()
    )
    directory = tmp_path / "protocol-test"
    return directory, json.loads((directory / "operator.yaml").read_text())


def test_skeleton_manifest_and_real_selftest(skeleton, monkeypatch):
    monkeypatch.setattr(runtime, "config", native_config)
    directory, manifest = skeleton
    assert validate_manifest(manifest)["schemaVersion"] == 2
    output = io.StringIO()
    call_command("check_operator", directory, stdout=output)
    assert "单行表格复制：通过" in output.getvalue()
    with pytest.raises(Exception, match="目标目录已存在"):
        call_command("new_operator", "protocol-test", directory=directory.parent)


def test_selftest_inputs_use_the_same_portable_snapshot_boundary_as_tasks(
    skeleton, monkeypatch
):
    monkeypatch.setattr(runtime, "config", native_config)
    execute = operator_checks.execute
    observed = []

    def inspect_inputs(attempt, package, inputs, outputs, manifest, heartbeat):
        request = json.loads((inputs / "context.json").read_text())
        for item in request["inputs"].values():
            assert item["path"].startswith("/inputs/")
            source = inputs / item["path"].removeprefix("/inputs/")
            assert source.is_file()
            assert checksum(source) == item["sha256"]
            observed.append(source)
        return execute(attempt, package, inputs, outputs, manifest, heartbeat)

    from apps.compute.packages import checksum

    monkeypatch.setattr(operator_checks, "execute", inspect_inputs)
    check_package(source_packages(skeleton[0])[0][1])
    assert observed


def test_repeated_inputs_have_runnable_selftest(skeleton, monkeypatch):
    monkeypatch.setattr(runtime, "config", native_config)
    directory, manifest = skeleton
    manifest["inputs"][0]["repeat"] = {"min": 1, "max": 2, "labelRequired": True}
    (directory / "operator.yaml").write_text(json.dumps(manifest))
    fixture = json.loads((directory / "selftest/smoke.json").read_text())
    fixture["inputs"]["source"] = [{**fixture["inputs"]["source"], "label": "样例"}]
    fixture["fieldMappings"] = {"source__1": {"name": "title"}}
    (directory / "selftest/smoke.json").write_text(json.dumps(fixture))
    (directory / "main.py").write_text(
        "import shutil\nfrom operator_sdk import repeated_inputs\ndef run(context):\n    members = repeated_inputs(context, 'source')\n    assert members[0]['label'] == '样例'\n    assert members[0]['fieldMappings'] == {'name': 'title'}\n    shutil.copyfile(members[0]['path'], context.output_path('result.csv'))\n"
    )
    check_package(source_packages(directory)[0][1])


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda value: value.update(schemaVersion=3), "schemaVersion"),
        (
            lambda value: value["capabilities"].update(operations=["guess"]),
            "operations",
        ),
        (
            lambda value: value["capabilities"].update(dataTypes=["unknown"]),
            "dataTypes",
        ),
        (
            lambda value: value["inputs"][0]["fields"][0].update(types=["float"]),
            "types",
        ),
        (lambda value: value["inputs"][0]["fields"][0].update(min="bad"), "有限数字"),
        (
            lambda value: value["inputs"][0].update(
                crs={"mode": "same_as", "input": "absent"}
            ),
            "crs.input",
        ),
        (
            lambda value: value["inputs"][0].update(
                repeat={"min": 2, "max": 1, "labelRequired": True}
            ),
            "数量",
        ),
        (lambda value: value["outputs"][0].update(final="yes"), "布尔"),
        (lambda value: value["errors"][0].update(code="PLATFORM_OOM"), "PLATFORM_"),
        (lambda value: value["errors"][0].update(remedy="retry"), "补救类别"),
        (lambda value: value["resources"].update(memory="infinite"), "resources"),
        (lambda value: value["selfTests"][0].update(fixture="../secret"), "相对路径"),
        (
            lambda value: value["selfTests"][0]["expect"].update(errorCode="UNKNOWN"),
            "files或errorCode",
        ),
        (lambda value: value.update(version="1"), "语义化"),
    ],
)
def test_invalid_v2_manifest_has_actionable_message(skeleton, mutate, match):
    manifest = copy.deepcopy(skeleton[1])
    mutate(manifest)
    with pytest.raises(ComputeError, match=match):
        validate_manifest(manifest)


def test_v2_parameter_defaults_are_validated(skeleton):
    manifest = skeleton[1]
    manifest["parameters"] = [
        {
            "key": "threshold",
            "label": "阈值",
            "type": "number",
            "default": 3,
            "min": 0,
            "max": 1,
            "help": "单位区间",
            "agent": {"adjustable": True, "advice": "不得越界"},
        }
    ]
    with pytest.raises(ComputeError, match="范围"):
        validate_manifest(manifest)


def test_v1_opaque_annotations_keep_original_validation(skeleton):
    manifest = skeleton[1]
    manifest["schemaVersion"] = 1
    manifest["capabilities"] = "历史不透明扩展"
    manifest["inputs"][0].update(fields="历史自定义注解", repeat=True)
    manifest["outputs"][0].update(description="旧包已有说明", fields=None, final=None)
    result = validate_manifest(manifest)
    assert "capabilities" not in result
    assert result["inputs"][0]["fields"] == "历史自定义注解"
    flat, collections, _ = expand_bindings(result, {"source": 1})
    assert flat == {"source": 1} and collections == {}


def test_upload_requires_packaged_fixture(skeleton, tmp_path):
    directory, _ = skeleton
    data = source_packages(directory)[0][1]
    archive = tmp_path / "missing.zip"
    with (
        zipfile.ZipFile(io.BytesIO(data)) as original,
        zipfile.ZipFile(archive, "w") as target,
    ):
        for member in original.infolist():
            if not member.filename.startswith("selftest/"):
                target.writestr(member, original.read(member))
    with pytest.raises(ComputeError, match="缺少自检样例"):
        inspect_package(archive)


def test_selftest_does_not_swallow_runtime_unavailable(skeleton, monkeypatch):
    from apps.compute import operator_checks

    monkeypatch.setattr(runtime, "config", native_config)

    def unavailable(*args):
        raise ComputeError("受限运行环境不可用", 503)

    monkeypatch.setattr(operator_checks, "execute", unavailable)
    with pytest.raises(ComputeError, match="运行环境不可用"):
        check_package(source_packages(skeleton[0])[0][1])


def test_preflight_reports_missing_type_unit_and_crs(skeleton):
    manifest = validate_manifest(skeleton[1])
    spec = manifest["inputs"][0]
    spec["crs"] = {"mode": "projected"}
    spec["fields"][0]["unit"] = "m"
    metadata = {
        "source": {
            "kind": "table",
            "fields": ["name"],
            "bands": 0,
            "crs": "EPSG:4326",
            "fieldTypes": {"name": "integer"},
            "fieldUnits": {"name": "degree"},
        }
    }
    with pytest.raises(ComputeError) as missing:
        semantic_preflight(manifest, metadata, {}, {})
    assert {item["code"] for item in missing.value.gaps} == {
        "MISSING_ROLE",
        "CRS_MISMATCH",
    }
    with pytest.raises(ComputeError) as mismatch:
        semantic_preflight(manifest, metadata, {"source": {"name": "name"}}, {})
    assert {item["code"] for item in mismatch.value.gaps} == {
        "FIELD_TYPE",
        "FIELD_UNIT",
        "CRS_MISMATCH",
    }
    assert (
        next(item for item in mismatch.value.gaps if item["code"] == "FIELD_UNIT")[
            "actual"
        ]
        == "degree"
    )


def test_repeat_binding_and_legacy_ports_are_unchanged(skeleton):
    manifest = validate_manifest(skeleton[1])
    manifest["inputs"][0].update(
        required=False, repeat={"min": 0, "max": 2, "labelRequired": True}
    )
    bindings, collections, specs = expand_bindings(
        manifest, {"source": [{"resourceId": 2, "label": "石英"}]}
    )
    assert bindings == {"source__1": 2}
    assert collections == {"source": [{"key": "source__1", "label": "石英"}]}
    assert specs[0]["sourceKey"] == "source"
    with pytest.raises(ComputeError, match="唯一"):
        expand_bindings(
            manifest,
            {
                "source": [
                    {"resourceId": 2, "label": "石英"},
                    {"resourceId": 3, "label": "石英"},
                ]
            },
        )


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("reported", "MISSING_NAME"),
        ("crash", "PLATFORM_CRASH"),
        ("oom", "PLATFORM_OOM"),
        ("timeout", "PLATFORM_TIMEOUT"),
        ("invalid", "PLATFORM_INVALID_ERROR"),
    ],
)
def test_actual_runner_classifies_failures(
    skeleton, monkeypatch, tmp_path, kind, expected
):
    monkeypatch.setattr(runtime, "config", native_config)
    directory, manifest = skeleton
    statements = {
        "reported": "from operator_sdk import fail\nfail(context, 'MISSING_NAME', '缺少映射', remedy='complete_mapping', inputs=['source'])",
        "crash": "raise RuntimeError('private host traceback')",
        "oom": "raise MemoryError('private allocation')",
        "timeout": "import time\ntime.sleep(30)",
        "invalid": "context.output_path('__operator_error.json').write_text('{}')\nraise RuntimeError('invalid')",
    }
    (directory / "main.py").write_text(
        "def run(context):\n"
        + "\n".join("    " + line for line in statements[kind].splitlines())
    )
    inputs, outputs = tmp_path / "inputs", tmp_path / "outputs"
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "context.json").write_text(json.dumps({"inputs": {}, "parameters": {}}))
    manifest["timeoutSeconds"] = 1 if kind == "timeout" else 10
    state = runtime.inspect_runtime()
    with pytest.raises(ComputeError) as error:
        runtime.execute(
            SimpleNamespace(runtime_digest=state["imageDigest"]),
            directory,
            inputs,
            outputs,
            manifest,
            lambda: None,
        )
    assert error.value.failure["code"] == expected
    assert "private" not in error.value.failure["message"]


def test_invalid_reports_do_not_override_platform_codes(skeleton):
    manifest = skeleton[1]
    for raw in (b"{}", b"x" * 8193, b'{"code":"PLATFORM_OOM"}'):
        assert reported_failure(raw, manifest)["code"] == "PLATFORM_INVALID_ERROR"


@pytest.mark.parametrize(
    "name",
    [
        "geology-multi-check",
        "geology-multi-apply",
        "geology-multi-relations",
        "geology-multi-prospect",
        "input-adapters",
    ],
)
def test_upgraded_operator_selftests_execute(name, monkeypatch):
    monkeypatch.setattr(runtime, "config", native_config)
    for _, package in source_packages(ROOT / "examples/compute" / name):
        assert check_package(package)["schemaVersion"] == 2


def test_script_bridge_selftest_uses_real_isolation(monkeypatch):
    monkeypatch.setattr(runtime, "config", native_config)
    _, data = source_packages(ROOT / "examples/compute/data-script-bridge")[0]
    if not runtime.script_isolation_status()["available"]:
        pytest.skip("本机缺少受限脚本所需Linux内核隔离，禁止降级执行")
    assert check_package(data)["schemaVersion"] == 2


def test_geology_collection_exact_scientific_consistency(tmp_path, monkeypatch):
    from tests.unit.test_geology_multi_algorithms import (
        fixture,
        check,
        load,
        read,
        Context,
        KEYS,
    )

    monkeypatch.syspath_prepend(str(ROOT / "deploy/compute"))
    initial, _ = fixture(tmp_path)
    findings, quality = check(initial)
    labels = ["赤铁矿", "绿泥石", "水云母", "方解石", "白云石"]
    inputs = {key: value for key, value in initial.inputs.items() if key not in KEYS}
    entries = []
    for index, (key, label) in enumerate(zip(KEYS, labels), 1):
        actual = f"minerals__{index}"
        inputs[actual] = initial.inputs[key]
        entries.append({"key": actual, "label": label})
    collection = Context(tmp_path / "collection", inputs, initial.parameters)
    collection.input_collections = {"minerals": entries}
    load("check")(collection)
    assert findings == read(collection.output_path("issues.csv"))
    assert quality == json.loads(collection.output_path("quality.json").read_text())
    for filename in (
        "statistics.csv",
        "alteration_summary.csv",
        "alteration_quality.csv",
        "group_index.csv",
    ):
        assert read(initial.output_path(filename)) == read(
            collection.output_path(filename)
        )
    for suffix in ("before", "hits", "groups"):
        for key in KEYS:
            filename = f"{key}_{suffix}.tif"
            assert (
                collection.output_path(filename).read_bytes()
                == initial.output_path(filename).read_bytes()
            )
    import geopandas as gpd

    for original in initial.directory.glob("*.gpkg"):
        before = gpd.read_file(original)
        after = gpd.read_file(collection.output_path(original.name))
        assert before.crs == after.crs and before.equals(after)


def test_every_static_example_has_capabilities_and_output_semantics():
    for path in (ROOT / "examples/compute").glob("*/operator.yaml"):
        manifest = validate_manifest(yaml.safe_load(path.read_text()))
        assert manifest["capabilities"]["summary"]
        assert all(
            item["description"] and "fields" in item and "final" in item
            for item in manifest["outputs"]
        )


def test_open_collection_supports_unlisted_mineral(tmp_path, monkeypatch):
    from tests.unit.test_geology_multi_algorithms import fixture, load, Context, KEYS

    monkeypatch.syspath_prepend(str(ROOT / "deploy/compute"))
    initial, _ = fixture(tmp_path)
    inputs = {key: value for key, value in initial.inputs.items() if key not in KEYS}
    inputs["minerals__1"] = initial.inputs["hematite"]
    collection = Context(tmp_path / "quartz", inputs, initial.parameters)
    collection.input_collections = {
        "minerals": [{"key": "minerals__1", "label": "石英"}]
    }
    load("check")(collection)
    with (
        rasterio.open(collection.output_path("alteration_stack_before.tif")) as output,
        rasterio.open(inputs["minerals__1"]) as source,
    ):
        assert output.descriptions == ("石英",)
        assert output.crs == source.crs and output.transform == source.transform
        np.testing.assert_array_equal(
            output.read(1, masked=True), source.read(1, masked=True)
        )


def test_legacy_field_alias_views_preserve_original_file(
    skeleton, monkeypatch, tmp_path
):
    monkeypatch.syspath_prepend(str(ROOT / "deploy/compute"))
    from operator_sdk import bound_context

    source = tmp_path / "source.csv"
    source.write_text("地层,值\n甲,2\n", encoding="utf-8-sig")
    before = source.read_bytes()
    manifest = skeleton[1]
    manifest["inputs"][0]["fields"][0]["legacyName"] = "name"
    context = SimpleNamespace(
        field_mappings={"source": {"name": "地层"}}, input_path=lambda key: source
    )
    with bound_context(context, manifest) as bound:
        assert bound.input_path("source") != source
        assert (
            bound.input_path("source").read_text(encoding="utf-8-sig")
            == "name,值\n甲,2\n"
        )
    assert source.read_bytes() == before


@pytest.mark.efficiency
def test_semantic_preflight_does_not_read_pixels_or_rows(skeleton):
    manifest = validate_manifest(skeleton[1])
    metadata = {
        "source": {
            "kind": "table",
            "fields": ["name"],
            "bands": 0,
            "crs": "",
            "fieldTypes": {"name": "string"},
        }
    }
    mapping, parameters = semantic_preflight(
        manifest, metadata, {"source": {"name": "name"}}, {}
    )
    assert mapping == {"source": {"name": "name"}} and parameters == {}
