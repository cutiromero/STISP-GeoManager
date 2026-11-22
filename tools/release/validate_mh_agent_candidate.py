"""Required candidate acceptance for the native Qwen agent path."""

import argparse
import json
from pathlib import Path
import secrets
import sys

# Configuration
API = "/api/agent/hermes"
MODEL_TOOLS = {"search_resources", "list_business_flows", "describe_resource"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    context = json.loads(parser.parse_args().context.read_text(encoding="utf-8"))
    sys.path.insert(0, str(Path(context["code"]) / "backend"))

    import django

    django.setup()

    from django.contrib.auth import get_user_model
    from django.test import Client
    from apps.agent.models import HermesSession, HermesToolReceipt
    from apps.catalog.models import DataResource
    from apps.projects.context import ProjectScope, project_scope

    suffix = secrets.token_hex(6)
    token = "mhcandidate" + suffix
    resource_name = "样本-" + secrets.token_hex(6)
    user = get_user_model().objects.create_superuser("mh-probe-" + suffix)
    with project_scope(ProjectScope((1,), 1, user.id)):
        resource = DataResource.objects.create(
            name=resource_name,
            code=token,
            description=token,
            data_type="table",
            file_format="SQLITE",
            storage_path=token,
        )
    client = Client(HTTP_HOST="127.0.0.1", HTTP_X_PROJECT_ID="1")
    client.force_login(user)
    assert client.get(API + "/v1/capabilities").status_code == 200
    tools = client.get(API + "/v1/toolsets").json()["data"]
    enabled = {name for group in tools if group["enabled"] for name in group["tools"]}
    assert MODEL_TOOLS <= enabled, MODEL_TOOLS - enabled
    session = client.post(
        API + "/api/sessions", {"mode": "agent"}, content_type="application/json"
    )
    assert session.status_code == 201, session.status_code
    session_id = session.json()["session"]["id"]
    payload = {
        "session_id": session_id,
        "input": f"必须实际调用 search_resources，query 为 {token}，limit 为 5。读取返回的匹配项，然后将找到的资料名原样告知我。仅执行查询。",
    }
    idem = secrets.token_hex(16)
    run = client.post(
        API + "/v1/runs",
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idem,
    )
    assert run.status_code == 202, run.status_code
    run_id = run.json()["run_id"]
    path = API + "/v1/runs/" + run_id
    replay = client.post(
        API + "/v1/runs",
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idem,
    )
    assert (
        replay.status_code == 202
        and replay.json()["run_id"] == run_id
        and replay.json()["replayed"]
    )
    stream = client.get(path + "/events")
    assert stream.status_code == 200, stream.status_code
    frames = []
    for line in stream.streaming_content:
        if line.startswith(b"data: "):
            frames.append(json.loads(line[6:]))
    status = client.get(path).json()
    assert status["status"] == "completed", (
        status["status"],
        [f.get("event") for f in frames],
    )
    assert resource_name in status.get("output", ""), (
        "Qwen did not report the actual registered resource"
    )
    assert any(
        frame.get("tool") == "search_resources"
        and frame.get("event") == "tool.completed"
        and not frame.get("error")
        for frame in frames
    ), "missing original Hermes tool completion"
    session_row = HermesSession._base_manager.get(pk=session_id.removeprefix("stisp_"))
    receipt = HermesToolReceipt.objects.get(
        session=session_row, name="search_resources"
    )
    assert receipt.tool_call_id and any(
        item["resourceId"] == resource.pk for item in receipt.evidence
    )
    foreign = Client(HTTP_HOST="127.0.0.1", HTTP_X_PROJECT_ID="1")
    foreign.force_login(get_user_model().objects.create_superuser("mh-other-" + suffix))
    assert foreign.get(path).status_code == 404
    print(
        json.dumps(
            {
                "accepted": True,
                "checks": {
                    "nativeGateway": True,
                    "qwenToolCallAndReply": True,
                    "toolReceipt": True,
                    "idempotency": True,
                    "accountIsolation": True,
                },
            }
        )
    )


if __name__ == "__main__":
    main()
