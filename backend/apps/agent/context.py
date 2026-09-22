"""Budget the complete model request with the serving model's tokenizer."""

from .provider import ModelError, count_tokens


def prepare_context(messages, current, model, policy, window, thinking):
    output = policy["maxOutputTokens"]
    limit = min(policy["maxContextTokens"], window - output - 256)
    if limit < 256:
        raise ModelError("生成上限占满模型窗口，请降低生成上限或提高模型服务窗口")
    truncated = False

    def measure():
        return count_tokens(model, messages, thinking, policy["reasoningEffort"])

    def text_bytes():
        total = 0
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                total += len(content.encode("utf-8"))
            else:
                total += sum(len(p.get("text", "").encode("utf-8")) for p in content)
        return total

    tokens = measure()
    while tokens > limit or text_bytes() > policy["maxContextBytes"]:
        current_index = next(i for i, item in enumerate(messages) if item is current)
        if current_index > 1:
            # Previous conversation turns are user/assistant pairs.
            del messages[1 : min(3, current_index)]
        elif len(messages) > current_index + 3:
            # Remove an old tool call/result pair, retaining the latest pair.
            del messages[current_index + 1 : current_index + 3]
        else:
            content = current["content"]
            part = content[0] if isinstance(content, list) and content else None
            text = part.get("text", "") if part else ""
            marker = "\n\n【附件："
            if marker not in text:
                raise ModelError(
                    f"本轮输入需要 {tokens} token，可用 {limit}；请缩小附件、图片或工具结果范围"
                )
            prompt, attachment = text.split(marker, 1)
            ratio = min(
                limit / max(tokens, 1),
                policy["maxContextBytes"] / max(text_bytes(), 1),
                0.8,
            )
            keep = int(len(attachment) * ratio * 0.85)
            if keep < 64:
                raise ModelError("当前问题和图片已接近模型窗口，请减少图片或缩短问题")
            part["text"] = (
                prompt + marker + attachment[:keep] + "\n（附件已按模型窗口截断）"
            )
        truncated = True
        tokens = measure()
    return tokens, truncated
