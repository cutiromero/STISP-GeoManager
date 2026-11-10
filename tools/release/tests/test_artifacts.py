"""离线包、清单、路径与发布判定回归。"""

import io
import shutil
from pathlib import Path
import tarfile
import zipfile

import pytest

from tools.release import artifacts, server


def test_complete_delta_identical_and_removed_files(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "same.py").write_bytes(b"same")
    (base / "deleted.py").write_bytes(b"deleted")
    known = artifacts.tree_files(base)
    source = tmp_path / "source"
    source.mkdir()
    (source / "same.py").write_bytes(b"same")
    (source / "added.py").write_bytes(b"added")
    (source / "executable.sh").write_bytes(b"exit 0\n")
    (source / "executable.sh").chmod(0o755)
    files = artifacts.tree_files(source)

    def read(name):
        return (source / name).read_bytes()

    full = artifacts.write_package(files, read, tmp_path / "full.tar.gz")
    delta = artifacts.write_delta(files, known, read, tmp_path / "delta.zip")
    rebuilt = artifacts.apply_delta(
        base, tmp_path / delta["file"], tmp_path / "rebuilt.tar.gz", 100000
    )
    assert full["sha256"] == rebuilt["sha256"]
    assert full["bytes"] == rebuilt["bytes"]
    assert server.archive_files(tmp_path / full["file"], 100000) == files
    with zipfile.ZipFile(tmp_path / delta["file"]) as archive:
        assert "same.py" not in archive.namelist()
        assert "deleted.py" not in archive.namelist()


def test_delta_rejects_changed_baseline_and_symlink(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "same.py").write_bytes(b"same")
    files = artifacts.tree_files(base)
    artifacts.write_delta(
        files, files, lambda name: (base / name).read_bytes(), tmp_path / "delta.zip"
    )
    (base / "same.py").write_bytes(b"changed")
    with pytest.raises(server.ReleaseError, match="清单不一致"):
        artifacts.apply_delta(
            base, tmp_path / "delta.zip", tmp_path / "fail.tar.gz", 10000
        )
    (base / "same.py").unlink()
    (base / "same.py").symlink_to(tmp_path / "outside")
    with pytest.raises(server.ReleaseError, match="符号链接"):
        artifacts.apply_delta(
            base, tmp_path / "delta.zip", tmp_path / "link.tar.gz", 10000
        )


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "../out",
        "a/../../out",
        "a//b",
        "./a",
        ".",
        "",
        "C:/out",
        "a\\b",
        "a/\x00b",
        "config/release.local.toml",
        "app.toml",
        "secret.pem",
        "node_modules/x",
        ".runtime/token",
    ],
)
def test_unsafe_member_names(name):
    with pytest.raises(server.ReleaseError):
        server.safe_member(name)


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE]
)
def test_archive_rejects_links_special(tmp_path, kind):
    path = tmp_path / "bad.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        item = tarfile.TarInfo("safe")
        item.type = kind
        item.linkname = "../../outside"
        archive.addfile(item)
    with pytest.raises(server.ReleaseError, match="special"):
        server.archive_files(path, 10000)


@pytest.mark.parametrize(
    "duplicate,mode,limit",
    [(True, 0o644, 100), (False, 0o4644, 100), (False, 0o644, 1)],
)
def test_archive_duplicate_privilege_and_size(tmp_path, duplicate, mode, limit):
    path = tmp_path / "bad.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for index in range(2 if duplicate else 1):
            item = tarfile.TarInfo("safe")
            item.size, item.mode = 3, mode
            archive.addfile(item, io.BytesIO(b"abc"))
    with pytest.raises(server.ReleaseError):
        server.archive_files(path, limit)


def test_manifest_fingerprint_content_and_acceptance(layout):
    value, package = server.load_release(
        layout.config, layout.manifest, server.sha(layout.manifest)
    )
    assert value == layout.release and package == layout.package
    with pytest.raises(server.ReleaseError, match="fingerprint"):
        server.load_release(layout.config, layout.manifest, "0" * 64)
    layout.package.write_bytes(b"tampered")
    with pytest.raises(server.ReleaseError, match="size"):
        server.load_release(layout.config, layout.manifest, server.sha(layout.manifest))


@pytest.mark.parametrize(
    "field,value",
    [
        ("noSchemaChanges", False),
        ("scientificOperatorsUnchanged", False),
        ("ancestorVerified", False),
    ],
)
def test_server_cannot_bypass_fast_guards(layout, field, value):
    layout.release[field] = value
    server.write_json(layout.manifest, layout.release)
    with pytest.raises(server.ReleaseError):
        server.load_release(layout.config, layout.manifest, server.sha(layout.manifest))


def test_full_requires_exact_candidate_and_keeps_schema_gate(layout):
    release = layout.release
    release["mode"] = "full"
    release["candidateAcceptance"] = artifacts.acceptance(release, {"isolated": True})
    server.write_json(layout.manifest, release)
    server.load_release(layout.config, layout.manifest, server.sha(layout.manifest))
    release["candidateAcceptance"]["archiveSha256"] = "0" * 64
    server.write_json(layout.manifest, release)
    with pytest.raises(server.ReleaseError, match="Acceptance"):
        server.load_release(layout.config, layout.manifest, server.sha(layout.manifest))


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"migrations": ["x"]}, "迁移"),
        ({"scientificOperatorsUnchanged": False}, "算子"),
        ({"ancestorVerified": False}, "祖先"),
        ({}, None),
    ],
)
def test_fast_refusals(changes, expected):
    summary = {
        "migrations": [],
        "scientificOperatorsUnchanged": True,
        "ancestorVerified": True,
        **changes,
    }
    reasons = artifacts.fast_reasons(summary)
    assert (expected is None and not reasons) or expected in "；".join(reasons)


def test_reuse_checks_all_files_and_static_base(tmp_path):
    source = tmp_path / "source"
    (source / "frontend/dist/assets").mkdir(parents=True)
    (source / "frontend/dist/index.html").write_text(
        '<script src="/static/assets/x.js"></script>'
    )
    (source / "frontend/dist/assets/x.js").write_bytes(b"js")
    files = artifacts.tree_files(source)
    package = tmp_path / "base.tar.gz"
    artifacts.write_package(files, lambda name: (source / name).read_bytes(), package)
    root = tmp_path / "exported"
    root.mkdir()
    artifacts.reuse_dist(package, root, files, 10000)
    assert artifacts.validate_frontend(root, artifacts.tree_files(root)) == [
        "/static/assets/x.js"
    ]
    with pytest.raises(server.ReleaseError, match="摘要"):
        artifacts.reuse_dist(package, root, {}, 10000)


def test_diff_includes_deleted_renamed_migrations_and_actual_operator_paths(
    monkeypatch,
):
    paths = [
        "backend/apps/old/migrations/0002_deleted.py",
        "backend/apps/new/migrations/0002_renamed.py",
        "examples/compute/geology-multi-core/multi_checks.py",
        "backend/scripts/raster_symbolizers/basic_gradient.py",
        "frontend/pnpm-lock.yaml",
    ]
    calls = []

    def git(repo, *args, **kwargs):
        calls.append(args)
        return ("\0".join(paths) + "\0").encode()

    monkeypatch.setattr(artifacts, "git", git)
    monkeypatch.setattr(artifacts, "is_ancestor", lambda *args: False)
    summary = artifacts.diff_summary(Path("/repo"), "a" * 40, "b" * 40)
    assert summary["migrations"] == sorted(paths[:2])
    assert summary["scientific"] == sorted(paths[2:4])
    assert summary["frontendChanged"] is True
    assert summary["ancestorVerified"] is False
    assert "--no-renames" in calls[0]


def test_build_keeps_tracked_generated_docs_and_disables_install(
    tmp_path, config, monkeypatch
):
    frozen = tmp_path / "frozen"
    for name, text in {
        "backend/manage.py": "print('test')",
        "backend/pyproject.toml": '[project]\nversion="0.3.0"',
        "frontend/package.json": '{"version":"0.3.0"}',
        "frontend/generated/api-reference.html": "不可删除的已冻结文档",
    }.items():
        path = frozen / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    source_files = artifacts.tree_files(frozen)
    repo = tmp_path / "repo"
    (repo / "frontend/node_modules").mkdir(parents=True)
    for name in config["local"]["buildResources"]:
        resource = repo / name
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_bytes(b"local build image")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(
        artifacts, "export", lambda repo, commit, root: shutil.copytree(frozen, root)
    )
    monkeypatch.setattr(artifacts, "git_files", lambda *args: source_files)
    commands = []

    def build(command, **kwargs):
        commands.append(command)
        assert kwargs["env"]["pnpm_config_verify_deps_before_run"] == "false"
        assert kwargs["env"]["pnpm_config_manage_package_manager_versions"] == "false"
        assert kwargs["env"]["COREPACK_ENABLE_NETWORK"] == "0"
        frontend = Path(kwargs["cwd"])
        for name in config["local"]["buildResources"]:
            assert (frontend.parent / name).read_bytes() == b"local build image"
        (frontend / "dist/assets").mkdir(parents=True)
        (frontend / "dist/index.html").write_text(
            '<script src="/static/assets/x.js"></script>'
        )
        (frontend / "dist/assets/x.js").write_text("new js")

    monkeypatch.setattr(artifacts.subprocess, "run", build)
    artifact = artifacts.package_source(
        repo,
        "b" * 40,
        "a" * 40,
        work,
        config,
        {"frontendChanged": True},
        emit=lambda message: None,
    )
    assert commands == [[*config["local"]["pnpm"], "run", "build:verify"]]
    assert "frontend/generated/api-reference.html" in artifact["files"]
    assert not (work / "source/frontend/node_modules").exists()
    assert artifact["frontendReused"] is False
    assert set(artifact["timings"]) == {"导出", "前端构建或复用", "清单", "打包"}
    assert set(artifact["buildResources"]) == set(config["local"]["buildResources"])
    with tarfile.open(work / artifact["package"]["file"]) as archive:
        assert not set(config["local"]["buildResources"]) & set(archive.getnames())
    with zipfile.ZipFile(work / artifact["delta"]["file"]) as archive:
        assert not set(config["local"]["buildResources"]) & set(archive.namelist())
    for name, resource in artifact["buildResources"].items():
        assert resource["sha256"] == server.sha(repo / name)
        assert name not in artifact["files"]
        assert not (work / "source" / name).exists()


@pytest.mark.parametrize("missing_index", range(4))
def test_missing_local_build_resource_stops_before_build(
    tmp_path, config, monkeypatch, missing_index
):
    repo = tmp_path / "repo"
    repo.mkdir()
    missing = config["local"]["buildResources"][missing_index]
    for name in config["local"]["buildResources"]:
        if name != missing:
            resource = repo / name
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_bytes(b"local image")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(artifacts, "export", lambda repo, commit, root: root.mkdir())
    monkeypatch.setattr(artifacts, "git_files", lambda *args: {})
    monkeypatch.setattr(
        artifacts.subprocess, "run", lambda *args, **kwargs: pytest.fail("不能执行构建")
    )
    with pytest.raises(server.ReleaseError, match="缺少构建所需的本机资源") as caught:
        artifacts.package_source(
            repo, "b" * 40, "a" * 40, work, config, {"frontendChanged": True}
        )
    assert missing in str(caught.value)
    assert not (work / "release-code.tar.gz").exists()


def test_build_resources_cannot_overwrite_frozen_source(tmp_path):
    with pytest.raises(server.ReleaseError, match="不可覆盖已冻结源码"):
        artifacts.copy_build_resources(
            tmp_path,
            tmp_path / "source",
            ["frontend/source.ts"],
            {"frontend/source.ts": {}},
        )


def test_live_reuse_must_match_previous_staged_manifest(monkeypatch):
    source = {"backend/manage.py": {"sha256": "a" * 64, "bytes": 3, "mode": 0o644}}
    frontend = {
        "frontend/dist/index.html": {"sha256": "b" * 64, "bytes": 4, "mode": 0o644}
    }
    expected = {**source, **frontend}
    snapshot = {
        "commit": "c" * 40,
        "frontendFiles": frontend,
        "filesDigest": server.digest(expected),
    }
    calls = []

    def git_files(*args):
        calls.append(args)
        return source

    monkeypatch.setattr(artifacts, "git_files", git_files)
    assert artifacts.verified_baseline_files(Path("/repo"), snapshot) == expected
    assert len(calls) == 1
    snapshot["frontendFiles"] = {
        "frontend/dist/index.html": {"sha256": "0" * 64, "bytes": 4, "mode": 0o644}
    }
    with pytest.raises(server.ReleaseError, match="上一发布清单"):
        artifacts.verified_baseline_files(Path("/repo"), snapshot)


def test_missing_previous_manifest_digest_refuses_live_reuse(monkeypatch):
    monkeypatch.setattr(artifacts, "git_files", lambda *args: {})
    with pytest.raises(server.ReleaseError, match="上一发布清单"):
        artifacts.verified_baseline_files(
            Path("/repo"), {"commit": "a" * 40, "frontendFiles": {}}
        )
