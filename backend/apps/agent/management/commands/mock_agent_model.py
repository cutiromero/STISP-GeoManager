"""Deterministic OpenAI-compatible service for development; never used in production."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from django.core.management.base import BaseCommand


def mock_answer(body):
    messages = body.get("messages", [])
    if not body.get("response_format"):
        return "【本地开发模拟模型】已收到消息。这是用于验证界面、流式输出和取消的模拟回答。"
    previous = next(
        (m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""
    )
    try:
        action = json.loads(previous).get("action")
    except (ValueError, TypeError):
        action = None
    result = {}
    for m in reversed(messages):
        if m["content"].startswith("工具返回"):
            result = json.loads(m["content"].split("：", 1)[1])["result"]
            break
    if not action:
        command = {"action": "search_resources", "arguments": {"query": ""}}
    elif action == "search_resources":
        items = result.get("items", [])
        if not items:
            command = {"action": "final", "answer": "当前范围没有可分析的数据。"}
        else:
            command = {
                "action": "describe_resource",
                "arguments": {"resourceId": items[0]["id"]},
            }
    elif action == "describe_resource":
        command = {
            "action": "summarize_data",
            "arguments": {"resourceId": result["resource"]["id"]},
        }
    else:
        rows = ["| 字段 | 有效数 | 均值 |", "|---|---|---|"]
        rows += [
            f"| {s['field']} | {s['validCount']} | {s.get('mean', '不适用')} |"
            for s in result.get("statistics", [])
        ]
        command = {
            "action": "final",
            "answer": "【模拟模型】已按真实工具结果完成统计。\n"
            + "\n".join(rows)
            + "\n请查看证据面板中的统计口径。",
        }
    return json.dumps(command, ensure_ascii=False)


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"mock-local","max_model_len":32768}]}')

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 256000:
            self.send_error(413)
            return
        body = json.loads(self.rfile.read(length))
        if self.path == "/tokenize":
            # Mock-only deterministic budget, not a production tokenizer.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "count": len(
                            json.dumps(body.get("messages", []), ensure_ascii=False)
                        )
                    }
                ).encode()
            )
            return
        text = mock_answer(body)
        if body.get("chat_template_kwargs", {}).get("enable_thinking"):
            text = "<think>模拟思考片段。</think>" + text
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for offset in range(0, len(text), 4):
                data = {"choices": [{"delta": {"content": text[offset : offset + 4]}}]}
                self.wfile.write(("data: " + json.dumps(data) + "\n\n").encode())
                self.wfile.flush()
                time.sleep(0.025)
            self.wfile.write(
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class Command(BaseCommand):
    help = (
        "Serve a clearly labelled deterministic model on loopback for local development"
    )

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=19100)

    def handle(self, *args, **options):
        self.stdout.write(
            "Development mock model: http://127.0.0.1:%s/v1" % options["port"]
        )
        ThreadingHTTPServer(("127.0.0.1", options["port"]), MockHandler).serve_forever()
