import io
import json
import stat
import zipfile
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agent import workflow_roles
from apps.agent.models import AgentWorkflow, WorkflowUpload
from apps.agent.workflow_roles import validate_roles
from apps.compute.packages import ComputeError
from apps.projects.context import ProjectScope, project_scope
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_geology_generic_workflow import (
    GEOLOGY,
    geojson,
)
from tests.integration.test_geology_generic_workflow import generic as generic

pytestmark = pytest.mark.django_db


def archive(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, content in entries:
            zipped.writestr(name, content)
    return SimpleUploadedFile("总资料.zip", output.getvalue())


def unflagged_archive(entries, encoding):
    class UnflaggedZipInfo(zipfile.ZipInfo):
        def _encodeFilenameFlags(self):
            return self.filename.encode(encoding), self.flag_bits & ~0x800

    return archive([(UnflaggedZipInfo(name), content) for name, content in entries])


def post_batch(env, files):
    return env["client"].post(
        "/api/agent/workflow-uploads/batch/",
        {"batchId": env["batch"], "files": files},
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


def recognize(env):
    return env["client"].post(
        "/api/agent/workflow-uploads/recognize/",
        json.dumps({"batchId": env["batch"], "model": "mock"}),
        content_type="application/json",
        HTTP_X_PROJECT_ID=str(env["project"].id),
    )


@pytest.mark.parametrize("encoding", ["utf-8", "gbk"])
def test_unflagged_chinese_names_and_filename_role_hint(generic, encoding):
    names = ["海德乌拉_模拟识别岩性图.geojson", "海德乌拉_研究区.geojson"]
    uploaded = unflagged_archive(
        [(f"上传用/{name}", json.dumps(GEOLOGY)) for name in names], encoding
    )
    with zipfile.ZipFile(uploaded) as zipped:
        assert all(not entry.flag_bits & 0x800 for entry in zipped.infolist())
        assert all("海德乌拉" not in entry.filename for entry in zipped.infolist())
    uploaded.seek(0)
    response = post_batch(generic, [uploaded])
    assert response.status_code == 200, response.content
    value = response.json()
    assert value["errors"] == []
    assert {item["fileName"]: item["roleHint"] for item in value["items"]} == {
        names[0]: "lithology",
        names[1]: "coverage",
    }
    assert all(item["profile"]["featureCount"] == 4 for item in value["items"])


@pytest.mark.parametrize("encoding", ["utf-8", "gbk"])
@pytest.mark.parametrize("name", ["上传用/../越界.csv", "上传用\\..\\越界.csv"])
def test_unflagged_chinese_traversal_is_rejected(generic, encoding, name):
    response = post_batch(
        generic,
        [unflagged_archive([("正常.csv", "code\nA"), (name, "code\nA")], encoding)],
    )
    assert response.status_code == 200, response.content
    assert response.json()["items"] == []
    assert "不安全路径" in response.json()["errors"][0]["detail"]
    assert not WorkflowUpload._base_manager.filter(batch_id=generic["batch"]).exists()


def test_duplicate_paths_checked_after_filename_recovery(generic):
    output = io.BytesIO(unflagged_archive([("研究区.csv", "code\nA")], "gbk").read())
    with zipfile.ZipFile(output, "a") as zipped:
        zipped.writestr("研究区.csv", "code\nB")
    response = post_batch(generic, [SimpleUploadedFile("重复.zip", output.getvalue())])
    assert response.status_code == 200, response.content
    assert response.json()["items"] == []
    assert "重复路径" in response.json()["errors"][0]["detail"]
    assert not WorkflowUpload._base_manager.filter(batch_id=generic["batch"]).exists()


@pytest.mark.parametrize("flagged", [False, True])
def test_unrecoverable_or_flagged_names_are_unchanged(generic, flagged):
    name = "é.csv"
    entries = [(name, "code\nA")]
    uploaded = archive(entries) if flagged else unflagged_archive(entries, "cp437")
    response = post_batch(generic, [uploaded])
    assert response.status_code == 200, response.content
    assert response.json()["errors"] == []
    assert [item["fileName"] for item in response.json()["items"]] == [name]


def test_bundle_partial_registration_and_rule_roles(generic):
    response = post_batch(
        generic,
        [
            archive(
                [
                    ("资料/地质图.geojson", json.dumps(GEOLOGY)),
                    ("资料/单元.csv", "code,name\nA,测试组\n"),
                    ("资料/说明.txt", "unsupported"),
                    ("__MACOSX/._地质图", "ignore"),
                    (".DS_Store", "ignore"),
                    ("资料/地质图.shp.xml", "ignore"),
                    ("资料/图.tif.aux.xml", "ignore"),
                    ("资料/图.lock", "ignore"),
                ]
            )
        ],
    )
    assert response.status_code == 200, response.content
    value = response.json()
    assert len(value["items"]) == 2
    assert len(value["errors"]) == 1
    assert value["errors"][0]["fileName"] == "说明.txt"
    uploads = WorkflowUpload._base_manager.filter(batch_id=generic["batch"])
    assert uploads.count() == 2
    assert all(upload.resource.owner_only for upload in uploads)
    response = recognize(generic)
    assert response.status_code == 200, response.content
    value = response.json()
    assert value["source"] == "rules" and value["questions"] == []
    assert {item["role"] for item in value["items"]} == {"lithology", "units"}
    assert all("按文件名、类型和几何判断" in item["reason"] for item in value["items"])


@pytest.mark.parametrize(
    "name",
    [
        "../escape.csv",
        "/escape.csv",
        "C:/escape.csv",
        "folder/../../escape.csv",
        "..\\escape.csv",
    ],
)
def test_rejects_unsafe_archive_before_registration(generic, name):
    response = post_batch(
        generic,
        [
            archive(
                [
                    ("ok.csv", "code\nA"),
                    (name, "code\nA"),
                ]
            )
        ],
    )
    assert response.status_code == 200
    assert not response.json()["items"]
    assert "不安全路径" in response.json()["errors"][0]["detail"]
    assert not WorkflowUpload._base_manager.filter(batch_id=generic["batch"]).exists()


def test_rejects_symlinks_duplicates_and_entry_limit(generic, monkeypatch):
    link = zipfile.ZipInfo("link.csv")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    result = post_batch(generic, [archive([(link, "/etc/passwd")])]).json()
    assert "符号链接" in result["errors"][0]["detail"]
    result = post_batch(generic, [archive([("a.csv", "x"), ("A.csv", "x")])]).json()
    assert "重复路径" in result["errors"][0]["detail"]
    monkeypatch.setattr("apps.agent.workflow_bundles.MAX_ENTRIES", 1)
    result = post_batch(generic, [archive([("a.csv", "x"), ("b.csv", "x")])]).json()
    assert "条目" in result["errors"][0]["detail"]


def test_rejects_expanded_size_and_nested_archives(generic, monkeypatch):
    monkeypatch.setattr(
        "apps.agent.workflow_bundles.runtime_upload_max_mb", lambda: 0.001
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("a.csv", "x" * 2000)
    value = post_batch(
        generic, [SimpleUploadedFile("big.zip", output.getvalue())]
    ).json()
    assert "解压大小" in value["errors"][0]["detail"]
    value = post_batch(generic, [archive([("nested.zip", b"PK")])]).json()
    assert "嵌套ZIP" in value["errors"][0]["detail"]


def test_empty_zip_and_missing_shape_main_have_item_errors(generic):
    value = post_batch(generic, [archive([])]).json()
    assert value["items"] == [] and "没有可用资料" in value["errors"][0]["detail"]
    value = post_batch(generic, [archive([("map.dbf", b"data")])]).json()
    assert value["items"] == [] and "缺少.shp" in value["errors"][0]["detail"]


def test_shapefile_components_group_and_batch_limit(generic, tmp_path):
    import geopandas as gpd

    frame = gpd.GeoDataFrame.from_features(GEOLOGY["features"], crs="EPSG:4326")
    path = tmp_path / "地质图.shp"
    frame.to_file(path)
    shape = archive(
        [
            (f"nested/{part.name}", part.read_bytes())
            for part in tmp_path.iterdir()
            if part.is_file()
        ]
    )
    response = post_batch(generic, [shape])
    assert response.status_code == 200, response.content
    assert len(response.json()["items"]) == 1, response.content
    files = [
        SimpleUploadedFile(f"unit-{index}.csv", b"code\nA\n") for index in range(12)
    ]
    value = post_batch(generic, files).json()
    assert len(value["items"]) == 11
    assert len(value["errors"]) == 1 and "12" in value["errors"][0]["detail"]


def test_multiple_loose_files_and_shape_components(generic, tmp_path):
    import geopandas as gpd

    frame = gpd.GeoDataFrame.from_features(GEOLOGY["features"], crs="EPSG:4326")
    frame.to_file(tmp_path / "map.shp")
    files = [
        SimpleUploadedFile(part.name, part.read_bytes())
        for part in tmp_path.iterdir()
        if part.is_file()
    ]
    files.append(SimpleUploadedFile("units.csv", b"code\nA\n"))
    value = post_batch(generic, files).json()
    assert len(value["items"]) == 2 and value["errors"] == []


def test_same_shapefile_names_in_different_directories_are_distinct(generic, tmp_path):
    import geopandas as gpd

    frame = gpd.GeoDataFrame.from_features(GEOLOGY["features"], crs="EPSG:4326")
    frame.to_file(tmp_path / "map.shp")
    entries = [
        (f"{folder}/{part.name}", part.read_bytes())
        for folder in ("a", "b")
        for part in tmp_path.iterdir()
        if part.is_file()
    ]
    value = post_batch(generic, [archive(entries)]).json()
    assert len(value["items"]) == 2 and value["errors"] == []
    assert len({item["resourceId"] for item in value["items"]}) == 2


def test_model_role_validation_and_fallback(generic, monkeypatch):
    post_batch(generic, [geojson(), SimpleUploadedFile("units.csv", b"code\nA\n")])
    uploads = list(
        WorkflowUpload._base_manager.filter(batch_id=generic["batch"])
        .select_related("resource")
        .order_by("created_at")
    )
    items = [
        {"uploadId": str(upload.id), "role": role, "reason": "依据字段与几何"}
        for upload, role in zip(uploads, ["lithology", "units"], strict=True)
    ]
    monkeypatch.setattr(
        workflow_roles,
        "registry",
        lambda: {"mock": SimpleNamespace(model_id="real-test")},
    )
    monkeypatch.setattr(
        workflow_roles.provider,
        "stream",
        lambda *args, **kwargs: [json.dumps({"items": items})],
    )
    value = recognize(generic).json()
    assert value["source"] == "model" and value["questions"] == []
    for invalid in ["unknown", "units", "faults", ["lithology"]]:
        items[0]["role"] = invalid
        with pytest.raises(ComputeError):
            validate_roles(json.dumps({"items": items}), uploads)
        value = recognize(generic).json()
        assert value["source"] == "rules"
    monkeypatch.setattr(
        workflow_roles.provider,
        "stream",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            workflow_roles.provider.ModelError("offline")
        ),
    )
    assert recognize(generic).json()["source"] == "rules"


def test_missing_geology_duplicate_roles_and_model_identity(generic):
    post_batch(
        generic,
        [
            SimpleUploadedFile("a.csv", b"code\nA\n"),
            SimpleUploadedFile("b.csv", b"code\nB\n"),
        ],
    )
    value = recognize(generic).json()
    assert value["questions"]
    assert sum(item["role"] == "units" for item in value["items"]) == 1
    uploads = list(
        WorkflowUpload._base_manager.filter(batch_id=generic["batch"]).select_related(
            "resource"
        )
    )
    for items in [
        [
            {"uploadId": str(upload.id), "role": "units", "reason": "table"}
            for upload in uploads
        ],
        [{"uploadId": "not-real", "role": None, "reason": "?"}] * 2,
    ]:
        with pytest.raises(ComputeError):
            validate_roles(json.dumps({"items": items}), uploads)


def test_active_workflow_summary_is_owner_only_cross_project_and_cancelable(generic):
    scope = ProjectScope(
        (generic["project"].id,), generic["project"].id, generic["owner"].id
    )
    with project_scope(scope):
        workflow = AgentWorkflow.objects.create(
            owner=generic["owner"],
            model="mock",
            goal="旧任务。继续处理",
            workflow_type="research_processing",
            idempotency_key="old",
            status="paused",
        )
    headers = {"HTTP_X_PROJECT_ID": str(generic["project"].id)}
    response = generic["client"].get("/api/agent/workflows/active/", **headers)
    assert response.status_code == 200, response.content
    assert response.json()["item"] is None
    item = response.json()["parked"][0]
    assert item["id"] == str(workflow.id) and item["status"] == "paused"
    assert set(item) == {
        "id",
        "goal",
        "workflowType",
        "status",
        "updatedAt",
        "projectId",
        "conversationId",
        "conversationTitle",
    }
    response = generic["client"].post(
        f"/api/agent/workflows/{workflow.id}/cancel/",
        data="{}",
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200, response.content
    assert (
        generic["client"].get("/api/agent/workflows/active/", **headers).json()["item"]
        is None
    )
    AgentWorkflow._base_manager.filter(pk=workflow.pk).update(
        project_tag=generic["other_project"], status="running"
    )
    item = (
        generic["client"].get("/api/agent/workflows/active/", **headers).json()["item"]
    )
    assert item["projectId"] == generic["other_project"].id
    response = generic["client"].get(f"/api/agent/workflows/{workflow.id}/", **headers)
    assert response.status_code == 404
    AgentWorkflow._base_manager.filter(pk=workflow.pk).update(owner=generic["outsider"])
    assert (
        generic["client"].get("/api/agent/workflows/active/", **headers).json()["item"]
        is None
    )


def test_upload_and_role_permissions_and_bound_batch(generic):
    post_batch(generic, [geojson()])
    upload = WorkflowUpload._base_manager.get(batch_id=generic["batch"])
    workflow = AgentWorkflow._base_manager.create(
        owner=generic["owner"],
        project_tag=generic["project"],
        goal="已绑定",
        model="mock",
        idempotency_key="bound",
    )
    upload.workflow = workflow
    upload.save()
    assert post_batch(generic, [geojson()]).status_code == 409
    assert recognize(generic).status_code == 409
    generic["client"].force_login(generic["outsider"])
    response = recognize(generic)
    assert response.status_code in (400, 403, 404)
