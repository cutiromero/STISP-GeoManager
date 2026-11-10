"""按平台现有运行边界执行小样例，包内代码不在Django进程导入。"""

import csv
import io
import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import zipfile

from django.conf import settings

from .packages import ComputeError, checksum, inspect_package
from .preflight import expand_bindings
from .runtime import execute, inspect_runtime

MAX_FIXTURE_BYTES = 1024 * 1024


def source_packages(directory):
    directory = Path(directory).resolve()
    examples = Path(settings.PROGRAM_ROOT) / "examples/compute"
    if (
        directory.parent == examples
        and directory.name.startswith("geology-multi-")
        and directory.name != "geology-multi-core"
    ):
        builder = runpy.run_path(str(examples / "geology-multi-core/build.py"))
        return [(directory.name, builder["build"](directory.name))]
    if directory in {examples / "input-adapters", examples / "data-script-bridge"}:
        builder = runpy.run_path(str(directory / "build.py"))
        if "SPECS" in builder:
            return [(name, builder["build"](name)) for name in builder["SPECS"]]
        return [("input-data-script-bridge", builder["build"]())]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if any(
                part.startswith(".") or part == "__pycache__" for part in relative.parts
            ):
                continue
            if path.is_symlink():
                raise ComputeError("算子目录不允许符号链接")
            if path.is_file():
                archive.write(path, relative.as_posix())
    return [(directory.name, stream.getvalue())]


def fixture_bindings(fixture, manifest):
    declared = {item["key"]: item for item in manifest["inputs"]}
    sources, bindings = {}, {}
    for key, value in fixture["inputs"].items():
        if key not in declared:
            raise ComputeError("自检样例引用未声明输入：" + key)
        if "repeat" in declared[key]:
            if not isinstance(value, list):
                raise ComputeError("集合自检输入须为具名小样例数组：" + key)
            bindings[key] = []
            for source in value:
                if not isinstance(source, dict):
                    raise ComputeError("集合小样例须为对象")
                identifier = len(sources) + 1
                sources[identifier] = source
                bindings[key].append(
                    {"resourceId": identifier, "label": source.get("label", "")}
                )
        else:
            identifier = len(sources) + 1
            sources[identifier] = value
            bindings[key] = identifier
    flat, collections, specs = expand_bindings(manifest, bindings)
    kinds = {item["key"]: item["kind"] for item in specs}
    return (
        {key: sources[identifier] for key, identifier in flat.items()},
        collections,
        kinds,
    )


def validate_fixture(raw, manifest):
    if len(raw) > MAX_FIXTURE_BYTES:
        raise ComputeError("自检样例不可超过1 MiB")
    try:
        value = json.loads(raw)
        json.dumps(value, allow_nan=False)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise ComputeError("自检样例须为JSON") from error
    if (
        not isinstance(value, dict)
        or set(value) - {"inputs", "parameters", "fieldMappings"}
        or not isinstance(value.get("inputs"), dict)
        or not isinstance(value.get("parameters"), dict)
        or not isinstance(value.get("fieldMappings", {}), dict)
    ):
        raise ComputeError("自检样例须包含inputs、parameters对象")
    if set(value["parameters"]) - {item["key"] for item in manifest["parameters"]}:
        raise ComputeError("自检参数引用未声明的键")
    sources, _, kinds = fixture_bindings(value, manifest)
    for key, source in sources.items():
        if not isinstance(source, dict) or source.get("kind") != kinds[key]:
            raise ComputeError("自检样例输入类型不符：" + key)
        if source["kind"] not in {"table", "vector", "raster", "document", "gene"}:
            raise ComputeError("自检样例类型不受支持：" + source["kind"])
        if source["kind"] == "table" and (
            not isinstance(source.get("rows"), list)
            or any(not isinstance(row, dict) for row in source["rows"])
            or not source["rows"]
            and not source.get("columns")
        ):
            raise ComputeError("自检表格须包含rows；空表须声明columns")
        if source["kind"] == "vector" and (
            not isinstance(source.get("features"), list) or not source.get("crs")
        ):
            raise ComputeError("自检矢量须包含features及crs")
        if source["kind"] == "raster":
            shape, transform = source.get("shape"), source.get("transform")
            if (
                not isinstance(shape, list)
                or len(shape) != 2
                or any(type(size) is not int or not 1 <= size <= 128 for size in shape)
                or not isinstance(transform, list)
                or len(transform) != 6
                or not source.get("crs")
            ):
                raise ComputeError("自检栅格须含1至128像元shape、六项transform及crs")
        if source["kind"] in {"document", "gene"} and not isinstance(
            source.get("text"), str
        ):
            raise ComputeError("自检文档或基因须包含text")
    return value


def materialize_fixture(fixture, directory, manifest):
    inputs = {}
    sources, collections, _ = fixture_bindings(fixture, manifest)
    for key, source in sources.items():
        kind = source["kind"]
        suffix = {
            "table": ".csv",
            "vector": ".gpkg",
            "raster": ".tif",
            "document": ".txt",
            "gene": ".fasta",
        }[kind]
        target = directory / (key + suffix)
        if kind == "table":
            columns = source.get("columns") or list(source["rows"][0])
            with target.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, columns)
                writer.writeheader()
                writer.writerows(source["rows"])
        elif kind == "vector":
            import geopandas as gpd

            gpd.GeoDataFrame.from_features(
                source["features"], crs=source["crs"]
            ).to_file(target, layer="data", driver="GPKG", index=False)
        elif kind == "raster":
            import numpy as np
            import rasterio
            from affine import Affine

            height, width = source["shape"]
            if (
                type(height) is not int
                or type(width) is not int
                or not 1 <= height <= 128
                or not 1 <= width <= 128
            ):
                raise ComputeError("自检栅格单边须为1至128像元")
            values = np.full(
                (height, width),
                source.get("fill", 0),
                dtype=source.get("dtype", "uint8"),
            )
            for row, column, value in source.get("pixels", []):
                values[row, column] = value
            with rasterio.open(
                target,
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype=values.dtype,
                crs=source["crs"],
                transform=Affine(*source["transform"]),
                nodata=source.get("nodata"),
            ) as output:
                output.write(values, 1)
                if source.get("name"):
                    output.set_band_description(1, source["name"])
        else:
            target.write_text(source["text"], encoding="utf-8")
        inputs[key] = {"path": str(target.resolve()), "sha256": checksum(target)}
    return inputs, collections


def verify_summary(path, summary):
    if not path.is_file() or path.is_symlink():
        raise ComputeError("缺少自检期望输出：" + path.name)
    if "sha256" in summary and checksum(path) != summary["sha256"]:
        raise ComputeError(path.name + " 摘要不符")
    if "contains" in summary and summary["contains"] not in path.read_text(
        encoding="utf-8-sig"
    ):
        raise ComputeError(path.name + " 未包含期望内容")
    if "rows" in summary or "columns" in summary:
        if path.suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                columns, rows = reader.fieldnames, list(reader)
        elif path.suffix == ".gpkg":
            import geopandas as gpd

            frame = gpd.read_file(path)
            columns, rows = list(frame.columns), frame
        else:
            raise ComputeError(path.name + " 不能验证行/字段摘要")
        if (
            "rows" in summary
            and len(rows) != summary["rows"]
            or not set(summary.get("columns", [])) <= set(columns)
        ):
            raise ComputeError(path.name + " 行数或字段摘要不符")
    if "bands" in summary:
        import rasterio

        with rasterio.open(path) as source:
            if source.count != summary["bands"]:
                raise ComputeError(path.name + " 波段数量不符")


def check_package(data, *, emit=lambda message: None):
    with tempfile.TemporaryDirectory(prefix="operator-check-") as temporary:
        root = Path(temporary)
        archive, package = root / "operator.zip", root / "algorithm"
        archive.write_bytes(data)
        package.mkdir()
        manifest = inspect_package(archive, package)
        emit("清单与上传安全校验：通过")
        tests = manifest.get("selfTests", [])
        if not tests:
            emit("第1版清单：建议升级到第2版；未声明自检样例")
            return manifest
        runtime = inspect_runtime()
        if not runtime["ready"]:
            raise ComputeError("自检运行环境未就绪：" + runtime["detail"])
        attempt = SimpleNamespace(
            runtime_digest=runtime["imageDigest"],
            container_name="gm-selftest-" + root.name,
        )
        for index, test in enumerate(tests):
            inputs, outputs = root / f"inputs-{index}", root / f"outputs-{index}"
            inputs.mkdir()
            outputs.mkdir()
            fixture = validate_fixture(
                (package / test["fixture"]).read_bytes(), manifest
            )
            prepared, collections = materialize_fixture(fixture, inputs, manifest)
            request = {
                "inputs": prepared,
                "inputCollections": collections,
                "parameters": fixture["parameters"],
                "fieldMappings": fixture.get("fieldMappings", {}),
            }
            if (
                manifest["runtime"] == "python-data-script-v1"
                or manifest["schemaVersion"] == 2
            ):
                request["manifest"] = manifest
            (inputs / "context.json").write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8"
            )
            try:
                execute(attempt, package, inputs, outputs, manifest, lambda: None)
            except ComputeError as error:
                if "errorCode" not in test["expect"] or test["expect"]["errorCode"] != (
                    error.failure or {}
                ).get("code"):
                    raise
            else:
                if "errorCode" in test["expect"]:
                    raise ComputeError("自检应报告错误但实际成功")
                for output in manifest["outputs"]:
                    path = outputs / output["file"]
                    if output["required"] and not path.is_file():
                        raise ComputeError("缺少必需输出：" + output["file"])
                if manifest.get("qualityReport"):
                    from .quality import read_quality_report

                    read_quality_report(outputs, manifest)
                for filename, summary in test["expect"]["files"].items():
                    verify_summary(outputs / filename, summary)
            emit("自检 " + test["name"] + "：通过")
        return manifest
