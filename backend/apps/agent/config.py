"""Deployment-only registry: no client-supplied addresses and no GPU management."""

from dataclasses import dataclass
import tomllib
from urllib.parse import urlsplit

from django.conf import settings


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    name: str
    base_url: str
    model_id: str
    agent: bool = False
    qwen: bool = False
    # Vision is an explicit deployment capability.  A model name alone must
    # never make the server send image bytes to a text-only endpoint.
    vision: bool = False
    # The deployment contract currently uses a 32K context for the local
    # Qwen/Gemma services.  Keep this in the registry so the UI can show the
    # model window without exposing the private endpoint.
    context_window_tokens: int = 32768


def registry():
    override = getattr(settings, "AGENT_MODELS", None)
    if override is None:
        with settings.PROJECT_CONFIG.config_path.open("rb") as f:
            override = (
                tomllib.load(f)
                .get("application", {})
                .get("agent", {})
                .get("models", [])
            )
        if not override and getattr(settings, "DEBUG", False):
            override = [
                {
                    "alias": "mock",
                    "name": "本地开发模拟模型",
                    "base_url": "http://127.0.0.1:19100/v1",
                    "model_id": "mock-local",
                    "agent": True,
                    "qwen": False,
                }
            ]
    result = {}
    for raw in override:
        model = ModelConfig(**raw)
        url = urlsplit(model.base_url)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "::1"}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path.rstrip("/") != "/v1"
        ):
            raise ValueError("模型地址必须为已配置的本机 HTTP /v1 服务")
        if not model.alias or len(model.alias) > 80 or model.alias in result:
            raise ValueError("模型别名无效或重复")
        result[model.alias] = model
    return result
