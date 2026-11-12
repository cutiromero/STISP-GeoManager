"""Bind any number of declared classes into the geology operators' raster port."""

from pathlib import Path
import tempfile

from apps.compute.packages import ComputeError
from apps.core.data_adapters import combine_masks
from apps.core.storage import raster_source_path
from apps.raster.models import RasterDataset

from .geology_generic import MINERALS, LABELS, alteration_role
from .workflow_cancellation import check_cancelled


def supports_stack(workflow, user):
    from apps.compute.models import AlgorithmVersion
    from apps.compute.services import allowed_algorithms, agent_algorithm_allowed

    identifiers = {
        "geology-multi-check",
        "geology-multi-apply",
        "geology-multi-relations",
        "geology-multi-prospect",
    }
    frozen = workflow.plan.get("preparedAlgorithmFamily")
    if frozen:
        return bool(workflow.plan.get("usesClassMaskStack"))
    permitted = workflow.plan.get("chatExecution", {}).get("algorithmVersionIds")
    options = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            algorithm__identifier__in=identifiers,
            algorithm__enabled=True,
            algorithm__in=allowed_algorithms(),
            status="published",
        )
        .order_by("algorithm_id", "-created_at", "-id")
    )
    if permitted is not None:
        options = options.filter(pk__in=permitted)
    family = {}
    for row in options:
        if row.algorithm.identifier not in family and agent_algorithm_allowed(row):
            family[row.algorithm.identifier] = row
    stack_members = identifiers - {"geology-multi-relations"}
    stack = all(
        identifier in family
        and any(
            item["key"] == "alteration_stack"
            for item in family[identifier].manifest["inputs"]
        )
        for identifier in stack_members
    )
    if stack and set(family) == identifiers:
        workflow.plan["preparedAlgorithmFamily"] = {
            identifier: {"versionId": row.pk, "checksum": row.checksum}
            for identifier, row in family.items()
        }
        workflow.plan["usesClassMaskStack"] = True
    return stack and set(family) == identifiers


def canonical_label(value):
    """Known spelling aliases are compatibility hints, never a class allowlist."""
    label = str(value).strip().removesuffix("识别结果").removesuffix("识别")
    known = {LABELS[key].removesuffix("识别结果") for key in MINERALS}
    return label + "化" if label + "化" in known else label


def prepare_stack(workflow, user, sources, coverage):
    from apps.raster.services.importer import import_raster_file

    selected = {
        role: resource for role, resource in sources.items() if alteration_role(role)
    }
    datasets = {
        row.data_resource_id: row
        for row in RasterDataset.objects.filter(
            data_resource_id__in=[resource.pk for resource in selected.values()],
            status="ready",
        )
    }
    entries = []
    for role, resource in selected.items():
        if resource.data_type != "raster" or resource.pk not in datasets:
            raise ComputeError("输入适配尚未提供可用的分类掩膜：" + resource.name)
        dataset = datasets[resource.pk]
        tags = (dataset.source_gdalinfo or {}).get("metadata", {}).get("", {})
        adaptation = next(
            (
                entry
                for entry in workflow.plan.get("inputAdaptations", [])
                if entry["role"] == role
            ),
            {},
        )
        declared_label = adaptation.get("parameters", {}).get("label")
        original_name = adaptation.get("sourceName", resource.name)
        entries.append(
            {
                "path": raster_source_path(dataset.source_relative_path),
                "label": LABELS[role].removesuffix("识别结果")
                if role in MINERALS
                else canonical_label(declared_label)
                if declared_label and declared_label != original_name
                else canonical_label(original_name.rsplit("_", 1)[-1]),
                "forceLabel": tags.get("class_label_origin") == "source_name",
            }
        )
    with tempfile.TemporaryDirectory(prefix="geomanager-mask-stack-") as directory:
        path = Path(directory) / "class_masks.tif"
        details = combine_masks(
            entries,
            path,
            bounds=coverage.total_bounds,
            crs=coverage.crs,
            resolution=workflow.parameters.get("grid_resolution_m"),
            cancelled=lambda: check_cancelled(workflow),
            label_transform=canonical_label,
        )
        check_cancelled(workflow)
        dataset = import_raster_file(
            path,
            name="分类识别资料（工作副本）",
            raster_kind="categorical",
            resampling="nearest",
            uploader_id=user.pk,
            owner_only=True,
            resource_source=f"workflow-working:{workflow.pk}:alteration-stack",
        )
    resource = dataset.data_resource
    resource.is_compute_result = True
    resource.maintainer = user
    resource.description = (
        "由本次已授权来源生成的类别掩膜集合；类别不限于预置示例，原始资料保持不变。"
    )
    resource.save(
        update_fields=["is_compute_result", "maintainer", "description", "updated_at"]
    )
    workflow.plan["classMaskPreparation"] = {
        **details,
        "resourceId": resource.pk,
        "sourceResourceIds": [resource.pk for resource in selected.values()],
    }
    return resource
