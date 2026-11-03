"""Prepare rule-first map review inputs; keep acceptance material unregistered."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

ROI = (766465.899734376, 3973540.0897343755, 769265.899734376, 3976340.0897343755)
CENTER = (768465.899734376, 3975240.0897343755)
REGION = "青海东昆仑南坡"
SEEDS = {
    "fill_gap": "geology-review-20261014-complete-coverage",
    "set_age": "geology-review-20261014-babaoshan-age",
}
EXPANDED_VERSION = "expanded-20261025"
CASE_VERSIONS = {
    "natural-island-v1": {
        "roi": ROI,
        "features": 11,
        "code_prefix": "geology-review",
        "label_suffix": "",
        "gaps": [("geo-unit-00001", CENTER, (1, 1), 0)],
        "ages": ["geo-unit-00242"],
    },
    EXPANDED_VERSION: {
        "roi": (
            763665.899734376,
            3970740.0897343755,
            772065.899734376,
            3979140.0897343755,
        ),
        "features": 38,
        "code_prefix": "geology-review-expanded-20261025",
        "label_suffix": " 扩展区",
        "gaps": [
            ("geo-unit-00070", (765151.9431589821, 3973968.129821988), (0.8, 1), 0),
            ("geo-unit-00251", (769990.3318091418, 3977097.899927086), (1, 0.85), 1),
            ("geo-unit-00001", (767122.1416721693, 3975421.613798747), (1.1, 1.1), 2),
        ],
        "ages": ["geo-unit-00010", "geo-unit-00254"],
    },
}


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def knowledge():
    shared = {
        "domain": "geology",
        "status": "published",
        "ruleKind": "none",
        "ruleConfig": {},
        "category": "地质成果检查",
        "aliases": [],
    }
    return {
        "schemaVersion": 1,
        "batch": "geology-review-20261014",
        "entries": [
            {
                **shared,
                "seedKey": SEEDS["fill_gap"],
                "title": "完整制图范围内部漏填的条件化检查与填补（项目整理规则）",
                "subject": "内部漏填",
                "predicate": "满足覆盖与周界条件时建议填补",
                "object": "唯一包围图斑的稳定类别",
                "statement": "制图范围明确完整覆盖，排除了水体及未调查区，内部未分类空白的整个周界由同一有效地质图斑包围时，可建议沿用该图斑的稳定类别填补遗漏。面积只用于筛查，不单独决定类别。",
                "explanation": "这是本项目演示区整理的制图完整性规则。检查覆盖声明、例外范围、完整周界及唯一宿主，再形成建议；用户批准后执行填补并重新检查。规则不推断未知地质边界。",
                "conditions": [
                    "适用范围：本演示区明确完整覆盖的制图范围",
                    "覆盖资料明确无水体、无未调查区",
                    "空白位于范围内部且整个周界由同一稳定类别的唯一图斑包围",
                    "类别以class为键，name/code/path保持一致",
                ],
                "exceptions": [
                    "水体、未调查区和明确排除区保留",
                    "外边界空白、多类别周界或多个宿主需补资料复核",
                    "涉及构造边界或覆盖声明不充分时保留疑点",
                ],
                "aliases": [
                    "完整覆盖",
                    "未分类空白",
                    "内部漏填",
                    "填补空洞",
                    "制图完整性",
                ],
                "sources": [
                    {
                        "title": "项目整理的地质制图完整性检查规则",
                        "locator": "地质成果检查演示案例 / 规则1及覆盖与例外资料",
                        "url": "",
                        "excerpt": "限定于覆盖资料声明完整且无例外的内部空白；唯一图斑全周界包围。",
                    }
                ],
            },
            {
                **shared,
                "seedKey": SEEDS["set_age"],
                "title": "八宝山组地层名称与时代属性一致性（东昆仑南坡）",
                "subject": "八宝山组",
                "predicate": "辞书时代定义",
                "object": "晚三叠世（T3）",
                "statement": "中国岩石地层名称辞典条目06-63-0717将青海东昆仑南坡八宝山组的时代记为T3（晚三叠世）。采用该条目地层定义的图斑，其时代属性应与此口径一致。",
                "explanation": "晚三叠世是地层时代名称，T3是本图的时代编码。该检查比较已有地层名、适用地区与时代属性，建议更新矛盾属性，保留岩性、类别及边界。它是辞书定义的一致性检查。",
                "conditions": [
                    "适用地区：青海东昆仑南坡",
                    "采用八宝山组条目06-63-0717的地层定义",
                    "当前检查字段为geologic_age，采用辞书时代编码",
                    "资料中没有相反的可靠定年或地层重划证据",
                ],
                "exceptions": [
                    "其他地区同名地层分别处理",
                    "新的可靠定年证据或不同地层划分版本提交专家复核",
                    "名称或地区未明确时先补资料",
                ],
                "aliases": ["八宝山组", "地层时代", "T3", "晚三叠世", "时代属性一致性"],
                "sources": [
                    {
                        "title": "中国岩石地层名称辞典 / 八宝山组",
                        "locator": "条目06-63-0717；原材料条目9a3e4792f3014dfb94b7dc71bba33e55；时代、地区字段",
                        "url": "",
                        "excerpt": "时代：T3；地区：青海东昆仑南坡。",
                    }
                ],
            },
        ],
    }


def rules():
    common = {
        "region": REGION,
        "region_bbox_wgs84": "95,34,100,38",
        "expected_age_label": "",
        "age_labels_json": '{"T3":"晚三叠世","J3":"晚侏罗世"}',
    }
    return [
        {
            **common,
            "rule_id": "complete-coverage",
            "kind": "fill_gap",
            "name": "完整范围内部漏填检查",
            "scope": "本演示区明确完整覆盖范围",
            "conditions": "完整覆盖、无水体或未调查区、内部空白的整周界由唯一图斑包围",
            "exceptions": "排除区、外边界、多类或多宿主周界、构造边界保留复核",
            "evidence_id": "project-complete-coverage",
            "evidence_kind": "project_rule",
            "source": "项目整理的地质制图完整性检查规则",
            "source_locator": "规则1；覆盖与例外资料",
            "formation": "",
            "expected_age": "",
            "knowledge_seed": SEEDS["fill_gap"],
        },
        {
            **common,
            "rule_id": "babaoshan-age",
            "kind": "set_age",
            "name": "八宝山组时代定义",
            "scope": "采用该辞书定义的东昆仑南坡地层单元",
            "conditions": "地层名称及地区明确，采用辞书定义，未有相反定年证据",
            "exceptions": "不同地区同名地层、新定年或地层重划证据需复核",
            "evidence_id": "cgl-06-63-0717",
            "evidence_kind": "dictionary_definition",
            "source": "中国岩石地层名称辞典 / 八宝山组",
            "source_locator": "06-63-0717；时代、地区",
            "formation": "八宝山组",
            "expected_age": "T3",
            "expected_age_label": "晚三叠世",
            "knowledge_seed": SEEDS["set_age"],
        },
    ]


def natural_gap(
    center: tuple[float, float],
    grid_reference: Path,
    size: tuple[float, float] = (1, 1),
    variant: int = 0,
) -> tuple[Polygon, dict]:
    """Build one irregular island on the original classification's pixel grid."""
    with rasterio.open(grid_reference) as reference:
        grid = reference.transform
        if reference.crs is None or reference.crs.to_epsg() != 32646:
            raise ValueError("格网参照必须采用本案例的米制投影EPSG:32646")
        if grid.a <= 0 or grid.e >= 0 or grid.b != 0 or grid.d != 0:
            raise ValueError("格网参照需要无旋转的北向上分类栅格")
        # Asymmetric lobes form a natural outline; pixelization supplies the
        # same stair-step boundary as the surrounding classified map.
        profile = [
            (-8, -1),
            (-7, -4),
            (-5, -5),
            (-3, -7),
            (0, -6),
            (2, -8),
            (4, -6),
            (5, -3),
            (8, -2),
            (7, 1),
            (8, 3),
            (5, 4),
            (4, 6),
            (1, 7),
            (-1, 5),
            (-3, 6),
            (-4, 3),
            (-7, 3),
            (-6, 1),
        ]
        if any(not 0.5 <= value <= 1.5 for value in size) or variant not in (0, 1, 2):
            raise ValueError("岛状范围尺寸或形态超出已核对范围")
        if variant == 1:
            profile = [(-x, y) for x, y in profile]
        elif variant == 2:
            profile = [(y, -x) for x, y in profile]
        outline = Polygon(
            [
                (center[0] + x * grid.a * size[0], center[1] + y * -grid.e * size[1])
                for x, y in profile
            ]
        )
        extent = from_bounds(*outline.bounds, transform=grid)
        left, top = math.floor(extent.col_off) - 1, math.floor(extent.row_off) - 1
        width = math.ceil(extent.col_off + extent.width) - left + 1
        height = math.ceil(extent.row_off + extent.height) - top + 1
        if (
            left < 0
            or top < 0
            or left + width > reference.width
            or top + height > reference.height
        ):
            raise ValueError("演示位置超出格网参照的实际覆盖范围")
        local_grid = window_transform(Window(left, top, width, height), grid)
        mask = rasterize(
            [(outline, 1)],
            out_shape=(height, width),
            transform=local_grid,
            fill=0,
            dtype="uint8",
        )
        islands = [
            shape(geometry)
            for geometry, value in shapes(
                mask, mask=mask.astype(bool), transform=local_grid
            )
            if value == 1
        ]
        if len(islands) != 1 or islands[0].geom_type != "Polygon":
            raise ValueError("演示范围必须为一个边连通的有效岛状面")
        gap = islands[0]
        if not gap.is_valid or gap.interiors or gap.is_empty:
            raise ValueError("岛状范围不得包含无效几何或内部空洞")
        cells = int(mask.sum())
        if not 0 < gap.area < 300000 or not math.isclose(
            gap.area, cells * abs(grid.a * grid.e), abs_tol=0.001
        ):
            raise ValueError("岛状范围面积须与原生像元一致并满足现有筛查范围")
        return gap, {
            "shape": "irregular-native-grid-island-v1",
            "gridReference": str(grid_reference),
            "gridReferenceSha256": hashlib.sha256(
                grid_reference.read_bytes()
            ).hexdigest(),
            "gridTransform": list(grid)[:6],
            "gridCrs": reference.crs.to_string(),
            "gridCellSizeM": [grid.a, -grid.e],
            "gridCellCount": cells,
            "size": list(size),
            "variant": variant,
        }


def prepare(
    source,
    mapping_path,
    output,
    offset=(0, 0),
    structures=None,
    grid_reference=None,
    case_version=EXPANDED_VERSION,
):
    if case_version not in CASE_VERSIONS:
        raise ValueError("未知演示资料版本")
    case = CASE_VERSIONS[case_version]
    if grid_reference is None:
        raise ValueError("请提供原分类栅格作为格网参照，保留实际像元尺寸和对齐方式")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("运行资料目录已有内容，请选择新的版本目录")
    private = output.parent / (
        "acceptance-only" if offset == (0, 0) else "acceptance-variant"
    )
    if private.exists() and any(private.iterdir()):
        raise FileExistsError("独立验收目录已有内容，请选择新的版本目录")
    output.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    # Establish reviewed rules before constructing the matching input conditions.
    save_json(output / "expert_knowledge.json", knowledge())
    save_csv(output / "rules.csv", rules())
    mapping = {
        row["label"]: row
        for row in json.loads(mapping_path.read_text(encoding="utf-8-sig"))
    }
    frame = gpd.read_file(source).to_crs(32646)
    frame["feature_id"] = [f"geo-unit-{i:05d}" for i in range(len(frame))]
    frame["class"] = frame["class"].astype(int)
    for field in ("name", "code", "path"):
        frame[field] = frame["class"].map(lambda key: mapping[key][field])
    frame["formation"] = frame["name"].map(
        lambda name: "八宝山组" if name.startswith("八宝山组") else "其他地层单元"
    )
    frame["region"] = REGION
    frame["geologic_age"] = frame["formation"].map(
        lambda value: "T3" if value == "八宝山组" else "未指定"
    )
    frame = frame[
        [
            "feature_id",
            "class",
            "name",
            "code",
            "path",
            "formation",
            "region",
            "geologic_age",
            "geometry",
        ]
    ]
    area = box(*case["roi"])
    frame = frame[frame.intersects(area)].copy()
    frame.geometry = frame.geometry.intersection(area)
    assert len(frame) == case["features"] and frame.geometry.is_valid.all()
    assert area.difference(unary_union(frame.geometry)).area < 0.001
    frame.to_file(private / "reference.gpkg", layer="data", driver="GPKG", index=False)
    before = frame.copy(deep=True)
    gaps, gap_records = [], []
    for host_id, center, size, variant in case["gaps"]:
        actual_center = (center[0] + offset[0], center[1] + offset[1])
        gap, metadata = natural_gap(actual_center, grid_reference, size, variant)
        hosts = frame[frame.geometry.contains(gap)]
        assert len(hosts) == 1 and hosts.iloc[0].feature_id == host_id
        host = hosts.index[0]
        frame.at[host, "geometry"] = frame.loc[host].geometry.difference(gap)
        gaps.append(gap)
        gap_records.append(
            {
                "host": host_id,
                "center": actual_center,
                "areaM2": gap.area,
                "preparation": metadata,
            }
        )
    for age_id in case["ages"]:
        age_rows = frame[frame.feature_id == age_id]
        assert len(age_rows) == 1 and age_rows.iloc[0].formation == "八宝山组"
        assert age_rows.iloc[0].geologic_age == "T3"
        frame.loc[frame.feature_id == age_id, "geologic_age"] = "J3"
    frame.to_file(
        output / "待检查地质图.gpkg", layer="data", driver="GPKG", index=False
    )
    coverage = gpd.GeoDataFrame(
        {
            "coverage_id": ["review-area"],
            "role": ["coverage"],
            "complete_coverage": [True],
            "no_water": [True],
            "no_uninvestigated": [True],
            "region": [REGION],
            "source": ["地质成果检查演示案例 / 覆盖与例外资料"],
            "source_locator": ["范围记录1；本演示范围要求完整填图，无水体及未调查例外"],
        },
        geometry=[area],
        crs=32646,
    )
    if structures is not None:
        context = gpd.read_file(structures).to_crs(32646)
        context = context[context.intersects(area)]
        rows = []
        for i, row in context.iterrows():
            protection = row.geometry.buffer(15).intersection(area)
            if protection.is_empty:
                continue
            rows.append(
                {
                    "coverage_id": f"structure-protection-{i}",
                    "role": "exclusion",
                    "complete_coverage": False,
                    "no_water": False,
                    "no_uninvestigated": False,
                    "region": REGION,
                    "source": "区域地质解译成果 / 构造资料",
                    "source_locator": f"构造条目{row.get('structure_id', i)}；15米保护带，涉及此范围时保留审核",
                    "geometry": protection,
                }
            )
        if rows:
            exclusions = gpd.GeoDataFrame(rows, crs=32646)
            assert all(not exclusions.intersects(gap).any() for gap in gaps)
            coverage = gpd.GeoDataFrame(
                pd.concat([coverage, exclusions], ignore_index=True), crs=32646
            )
    coverage.to_file(
        output / "制图覆盖资料.gpkg", layer="data", driver="GPKG", index=False
    )
    save_json(
        private / "preparation.json",
        {
            "source": str(source),
            "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "caseVersion": case_version,
            "roi": case["roi"],
            "coverageAreaM2": area.area,
            "gaps": gap_records,
            "ageObjects": case["ages"],
            "correctAge": "T3",
            "unregistered": True,
            "derivedAttributes": "formation,region,geologic_age按辞书口径补录作为演示条件；并非新增野外实测",
            "ruleFirst": True,
            "structureSource": str(structures) if structures is not None else "",
            "structureExclusions": int((coverage.role == "exclusion").sum()),
        },
    )
    changed_ids = {item["host"] for item in gap_records} | set(case["ages"])
    for i, row in before.iterrows():
        if row.feature_id not in changed_ids:
            assert frame.loc[i].geometry.equals_exact(row.geometry, 0)
            assert frame.loc[i].drop("geometry").equals(row.drop("geometry"))
    descriptions = {
        "geology-review-initial": "演示案例的待检查地质图。稳定类别以class为键；地层和地区字段采用资料整理口径，用于检查制图与属性一致性。",
        "geology-review-coverage": "演示区完整覆盖，无水体和未调查区。构造资料对应的15米保护带以exclusion单独登记，涉及该范围时保留审核。"
        if structures is not None
        else "演示区的完整制图覆盖范围及例外声明：本范围完整覆盖，无水体和未调查区。",
        "geology-review-rules": "专家知识对应的结构化检查条件、建议处理与例外；修改前需要用户批准。",
    }
    files = [
        ("geology-review-initial", "待检查地质图", "待检查地质图.gpkg", "vector"),
        ("geology-review-coverage", "制图覆盖资料", "制图覆盖资料.gpkg", "vector"),
        ("geology-review-rules", "专家知识检查规则", "rules.csv", "table"),
    ]
    manifest = {
        "schemaVersion": 1,
        "resources": [
            {
                "code": code.replace("geology-review", case["code_prefix"], 1),
                "name": name + case["label_suffix"],
                "file": file,
                "kind": kind,
                "layer": "data",
                "sha256": hashlib.sha256((output / file).read_bytes()).hexdigest(),
                "description": descriptions[code],
            }
            for code, name, file, kind in files
        ],
        "algorithms": ["geology-map-check", "geology-map-correct"],
        "caseVersion": case_version,
    }
    save_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "features": len(frame),
                "classes": sorted(set(frame["class"].tolist())),
                "caseVersion": case_version,
                "coverageAreaKm2": area.area / 1e6,
                "gapAreasM2": [gap.area for gap in gaps],
                "issueCount": len(gaps) + len(case["ages"]),
                "unchangedFeatures": len(frame) - len(changed_ids),
                "runtimeDirectory": str(output),
                "acceptanceDirectory": str(private),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--offset", type=float, nargs=2, default=(0, 0))
    parser.add_argument("--structures", type=Path)
    parser.add_argument("--grid-reference", type=Path, required=True)
    parser.add_argument(
        "--case-version", choices=CASE_VERSIONS, default=EXPANDED_VERSION
    )
    args = parser.parse_args()
    prepare(
        args.source,
        args.mapping,
        args.output,
        tuple(args.offset),
        args.structures,
        args.grid_reference,
        args.case_version,
    )
