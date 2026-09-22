from __future__ import annotations

import hashlib
import hmac
import http.client
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, urlparse

from django.conf import settings

from apps.core.backup_config import (
    LocalBackupTargetSettings,
    ObjectStorageBackupSettings,
)
from apps.core.storage import app_path


class BackupTargetError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredBackup:
    local_path: str = ""
    object_key: str = ""


class LocalBackupTarget:
    def __init__(self, config: LocalBackupTargetSettings):
        self.config = config

    @property
    def root(self) -> Path:
        if not self.config.directory:
            return app_path("backups", "local")
        root = Path(self.config.directory).expanduser().resolve()
        if _is_relative_to(root, settings.PROGRAM_ROOT):
            raise BackupTargetError("本地备份目录不能位于程序目录内")
        return root

    def test_connection(self) -> None:
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise BackupTargetError("本地备份目录不可用")
        probe = root / f".backup-test-{uuid.uuid4().hex}.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            if probe.read_text(encoding="utf-8") != "ok":
                raise BackupTargetError("本地备份目录读写校验失败")
        finally:
            if probe.exists():
                probe.unlink()

    def store(
        self, archive_path: Path, plan_type: str, archive_name: str
    ) -> StoredBackup:
        root = self.root
        target_dir = root / plan_type
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / archive_name
        if archive_path.resolve() != target_path.resolve():
            shutil.copy2(archive_path, target_path)
        return StoredBackup(local_path=str(target_path))

    def delete(self, plan_type: str, archive_name: str) -> None:
        path = self.root / plan_type / archive_name
        if path.is_file():
            path.unlink()


class ObjectStorageBackupTarget:
    def __init__(self, config: ObjectStorageBackupSettings):
        self.config = config
        if not config.configured:
            raise BackupTargetError("对象存储参数未配置完整")
        parsed = urlparse(config.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BackupTargetError("对象存储 endpoint 必须是 http 或 https 地址")
        self._parsed_endpoint = parsed

    def test_connection(self) -> None:
        key = self.object_key("_probe", f"connection-test-{uuid.uuid4().hex}.txt")
        self.put_bytes(key, b"ok")
        self.delete(key)

    def store(
        self, archive_path: Path, plan_type: str, archive_name: str
    ) -> StoredBackup:
        key = self.object_key(plan_type, archive_name)
        self.put_file(key, archive_path)
        return StoredBackup(object_key=key)

    def object_key(self, plan_type: str, archive_name: str) -> str:
        now = datetime.now()
        prefix = self.config.prefix.strip().strip("/")
        parts = [
            part
            for part in (prefix, plan_type, f"{now:%Y}", f"{now:%m}", archive_name)
            if part
        ]
        return "/".join(parts)

    def put_bytes(self, key: str, data: bytes) -> None:
        payload_hash = hashlib.sha256(data).hexdigest()
        self._request("PUT", key, payload_hash, len(data), data=data)

    def put_file(self, key: str, path: Path) -> None:
        payload_hash = _file_sha256(path)
        with path.open("rb") as handle:
            self._request("PUT", key, payload_hash, path.stat().st_size, fileobj=handle)

    def delete(self, key: str) -> None:
        payload_hash = hashlib.sha256(b"").hexdigest()
        self._request("DELETE", key, payload_hash, 0)

    def _request(
        self,
        method: str,
        key: str,
        payload_hash: str,
        content_length: int,
        *,
        data: bytes | None = None,
        fileobj: BinaryIO | None = None,
    ) -> None:
        parsed = self._parsed_endpoint
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        datestamp = timestamp[:8]
        path = self._canonical_path(key)
        host = parsed.netloc
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": timestamp,
        }
        if method == "PUT":
            headers["content-length"] = str(content_length)
            headers["content-type"] = "application/zip"
        authorization = self._authorization(
            method,
            path,
            headers,
            payload_hash,
            datestamp,
        )
        headers["authorization"] = authorization

        connection_cls = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_cls(host, timeout=30)
        try:
            connection.putrequest(method, path)
            for key_name, value in headers.items():
                connection.putheader(key_name, value)
            connection.endheaders()
            if data is not None:
                connection.send(data)
            elif fileobj is not None:
                while chunk := fileobj.read(1024 * 1024):
                    connection.send(chunk)
            response = connection.getresponse()
            body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise BackupTargetError(
                    f"对象存储请求失败：HTTP {response.status} {body[:240]}"
                )
        finally:
            connection.close()

    def _canonical_path(self, key: str) -> str:
        endpoint_path = self._parsed_endpoint.path.strip("/")
        raw = "/".join(
            part for part in (endpoint_path, self.config.bucket.strip("/"), key) if part
        )
        return "/" + quote(raw, safe="/-_.~")

    def _authorization(
        self,
        method: str,
        canonical_uri: str,
        headers: dict[str, str],
        payload_hash: str,
        datestamp: str,
    ) -> str:
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(
            f"{name}:{headers[name].strip()}\n" for name in sorted(headers)
        )
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{datestamp}/{self.config.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                headers["x-amz-date"],
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _signature_key(
            self.config.secret_access_key,
            datestamp,
            self.config.region,
            "s3",
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.config.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )


def _signature_key(secret_key: str, datestamp: str, region: str, service: str) -> bytes:
    key_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    key_region = _sign(key_date, region)
    key_service = _sign(key_region, service)
    return _sign(key_service, "aws4_request")


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True
