from openai import OpenAI

from core.get_config import Config


def _extract_text(value):
    """把字符串或分片列表统一整理成纯文本。"""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _extract_reasoning(delta):
    """兼容不同字段名的思考内容。"""
    for field_name in ("reasoning_content", "reasoning", "thinking"):
        text = _extract_text(getattr(delta, field_name, None))
        if text:
            return text
    return ""


def call_llm(
    message,
    model: str,
    apikey: str,
    stream: bool = False,
    on_token=None,
    on_reasoning_token=None,
    thinking_enabled: bool = True,
    reasoning_effort: str | None = "high",
):
    """统一封装主对话与摘要模型调用。"""
    current_agent = Config().agent
    client = OpenAI(
        api_key=apikey,
        base_url="https://api.deepseek.com",
    )
    request_kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": current_agent["system"]},
            {"role": "user", "content": message},
        ],
        "stream": stream,
    }
    if reasoning_effort:
        request_kwargs["reasoning_effort"] = reasoning_effort
    if thinking_enabled:
        request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    response = client.chat.completions.create(**request_kwargs)

    if not stream:
        message_obj = response.choices[0].message
        return _extract_text(getattr(message_obj, "content", None)).strip()

    chunks = []
    for event in response:
        if not event.choices:
            continue

        delta = event.choices[0].delta
        reasoning = _extract_reasoning(delta)
        if reasoning and on_reasoning_token is not None:
            on_reasoning_token(reasoning)

        content = _extract_text(getattr(delta, "content", None))
        if content:
            chunks.append(content)
            if on_token is not None:
                on_token(content)

    return "".join(chunks)
