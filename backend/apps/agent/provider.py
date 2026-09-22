import http.client
import json
import socket
import threading
from urllib.parse import urlsplit


class ModelError(Exception):
    pass


def model_request(model, path, body=None):
    url = urlsplit(model.base_url)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=20)
    try:
        conn.request(
            "POST" if body is not None else "GET",
            path,
            body=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        if response.status != 200:
            raise ModelError("模型窗口或分词服务不可用，请管理员检查服务兼容性")
        return json.loads(response.read(16 * 1024 * 1024))
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise ModelError("无法核实模型窗口或输入 token 数，请稍后重试") from exc
    finally:
        conn.close()


def model_window(model):
    data = model_request(model, "/v1/models")
    for item in data.get("data", []):
        if item.get("id") == model.model_id:
            value = item.get("max_model_len")
            if type(value) is int and value > 0:
                return value
    raise ModelError("模型服务未提供实际上下文窗口，请管理员检查部署")


def count_tokens(model, messages, thinking=False, effort="medium"):
    body = {
        "model": model.model_id,
        "messages": messages,
        "add_generation_prompt": True,
    }
    if model.qwen:
        body["chat_template_kwargs"] = {
            "enable_thinking": thinking,
            "reasoning_effort": effort,
        }
    value = model_request(model, "/tokenize", body).get("count")
    if type(value) is not int or value < 0:
        raise ModelError("模型分词服务返回了无效的 token 数")
    return value


def check_model(model):
    url = urlsplit(model.base_url)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
    try:
        conn.request("GET", url.path.rstrip("/") + "/models")
        response = conn.getresponse()
        if response.status != 200:
            return False
        data = response.read(65537)
        if len(data) > 65536:
            return False
        return any(
            m.get("id") == model.model_id for m in json.loads(data).get("data", [])
        )
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def stream(
    model,
    messages,
    max_tokens,
    guard,
    structured=False,
    thinking=False,
    temperature=0.2,
    top_p=0.9,
    on_thinking=None,
    reasoning_effort="medium",
    on_usage=None,
):
    """No proxies/redirects; cancellation shuts down the upstream socket."""
    url = urlsplit(model.base_url)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=15)
    body = {
        "model": model.model_id,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream_options": {"include_usage": True},
    }
    if model.qwen:
        body["chat_template_kwargs"] = {
            "enable_thinking": thinking,
            "reasoning_effort": reasoning_effort,
        }
    if structured:
        body["response_format"] = {"type": "json_object"}
    done = threading.Event()
    failures = []
    sock = None

    def monitor():
        from django.db import close_old_connections

        try:
            while not done.wait(0.5):
                try:
                    guard()
                except Exception as exc:
                    failures.append(exc)
                    if sock:
                        try:
                            sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    return
        finally:
            close_old_connections()

    thread = None
    try:
        guard()
        conn.connect()
        sock = conn.sock
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        conn.request(
            "POST",
            url.path.rstrip("/") + "/chat/completions",
            body=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        if response.status != 200:
            raise ModelError("模型服务拒绝了本次请求，请缩短问题或稍后重试")
        total = 0
        complete = False
        inline_buffer = ""
        in_thinking = False
        # vLLM/Qwen may omit the opening marker but still emit </think>.
        saw_reasoning_field = False
        implicit_thinking = thinking
        length_limited = False

        def emit_thinking(text):
            if text and on_thinking:
                on_thinking(text)

        def emit_content(text):
            nonlocal inline_buffer, in_thinking, implicit_thinking
            if not text:
                return ""
            inline_buffer += text
            output = []
            while inline_buffer:
                if implicit_thinking and not saw_reasoning_field and not in_thinking:
                    explicit = inline_buffer.lower().find("<think>")
                    closing = inline_buffer.lower().find("</think>")
                    if closing >= 0 and (explicit < 0 or closing < explicit):
                        emit_thinking(inline_buffer[:closing])
                        inline_buffer = inline_buffer[closing + 8 :]
                        implicit_thinking = False
                        continue
                    if explicit < 0:
                        # Preserve streamed reasoning even if the generation
                        # ends before its closing marker. Retain split tags only.
                        keep = max(0, len(inline_buffer) - 8)
                        emit_thinking(inline_buffer[:keep])
                        inline_buffer = inline_buffer[keep:]
                        break
                    implicit_thinking = False
                if in_thinking:
                    end = inline_buffer.lower().find("</think>")
                    if end < 0:
                        keep = max(0, len(inline_buffer) - 8)
                        emit_thinking(inline_buffer[:keep])
                        inline_buffer = inline_buffer[keep:]
                        break
                    emit_thinking(inline_buffer[:end])
                    inline_buffer = inline_buffer[end + 8 :]
                    in_thinking = False
                else:
                    start = inline_buffer.lower().find("<think>")
                    if start < 0:
                        # Keep a possible split opening marker across SSE
                        # fragments instead of leaking half a tag.
                        keep = 7 if thinking else 0
                        if keep and len(inline_buffer) > keep:
                            output.append(inline_buffer[:-keep])
                            inline_buffer = inline_buffer[-keep:]
                        else:
                            output.append(inline_buffer)
                            inline_buffer = ""
                        break
                    if start:
                        output.append(inline_buffer[:start])
                        inline_buffer = inline_buffer[start:]
                        continue
                    inline_buffer = inline_buffer[7:]
                    in_thinking = True
            return "".join(output)

        while True:
            guard()
            line = response.readline(65537)
            if not line:
                break
            if len(line) > 65536:
                raise ModelError("模型响应超出限制")
            total += len(line)
            if total > 2 * 1024 * 1024:
                raise ModelError("模型响应过大")
            if line.strip() == b"data: [DONE]":
                complete = True
                break
            if not line.startswith(b"data: "):
                continue
            payload = json.loads(line[6:])
            if payload.get("usage") and on_usage:
                on_usage(payload["usage"])
            choices = payload.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            content = choice.get("delta", {}).get("content")
            delta = choice.get("delta", {})
            reasoning = (
                delta.get("reasoning_content")
                or delta.get("reasoning")
                or delta.get("thinking")
            )
            if reasoning:
                if not isinstance(reasoning, str):
                    raise ModelError("模型思考响应格式错误")
                saw_reasoning_field = True
                emit_thinking(reasoning)
            if content:
                if not isinstance(content, str):
                    raise ModelError("模型文本响应格式错误")
                emitted = emit_content(content)
                if emitted:
                    yield emitted
            if choice.get("finish_reason") == "length":
                length_limited = True
        if inline_buffer:
            if in_thinking or (implicit_thinking and not saw_reasoning_field):
                emit_thinking(inline_buffer)
            else:
                yield inline_buffer
        if failures:
            raise failures[0]
        if length_limited:
            raise ModelError(
                "思考与正文已达到本次生成 token 上限；已生成内容已保留，可降低思考强度或提高生成上限后重试"
            )
        if not complete:
            raise ModelError("模型连接提前中断，内容未完成")
    except (OSError, ValueError, http.client.HTTPException) as exc:
        if failures:
            raise failures[0]
        raise ModelError("模型连接中断或超时，请重试") from exc
    finally:
        done.set()
        conn.close()
        if thread:
            thread.join(timeout=2)
