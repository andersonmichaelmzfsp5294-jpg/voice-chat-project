import json

import httpx

from config import (
    ARK_API_KEY,
    ARK_MODEL,
    ARK_BASE_URL,
    ARK_TIMEOUT_SEC,
    ARK_MAX_TOKENS,
    ARK_SYSTEM_PROMPT,
)
from utils import make_user_message


def require_ark_env():
    missing = []

    if not ARK_API_KEY:
        missing.append("ARK_API_KEY")
    if not ARK_MODEL:
        missing.append("ARK_MODEL")
    if not ARK_BASE_URL:
        missing.append("ARK_BASE_URL")

    if missing:
        raise RuntimeError(f"缺少 Ark 环境变量：{', '.join(missing)}")


async def build_chat_messages(
    session_id: str,
    user_text: str,
    history_provider,
    system_prompt: str = ARK_SYSTEM_PROMPT,
) -> list[dict[str, str]]:
    history = await history_provider(session_id)
    return [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_text},
    ]


async def call_chat_model(messages: list[dict[str, str]]) -> str:
    require_ark_env()

    url = f"{ARK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": ARK_MODEL,
        "messages": messages,
        "max_tokens": ARK_MAX_TOKENS,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=ARK_TIMEOUT_SEC) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code != 200:
        raise RuntimeError(f"Ark 调用失败：HTTP {resp.status_code} {resp.text[:1500]}")

    data = resp.json()

    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"Ark 返回格式异常：{str(data)[:1500]}")

    if text is None:
        raise RuntimeError("Ark 返回内容为空。")

    if isinstance(text, list):
        text = "".join(
            part.get("text", "")
            for part in text
            if isinstance(part, dict)
        )

    text = str(text).strip()
    if not text:
        raise RuntimeError("Ark 返回空字符串。")

    return text


async def iter_ark_stream(messages: list[dict[str, str]]):
    require_ark_env()

    url = f"{ARK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": ARK_MODEL,
        "messages": messages,
        "max_tokens": ARK_MAX_TOKENS,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=ARK_TIMEOUT_SEC) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                error_text = await resp.aread()
                raise RuntimeError(
                    f"Ark 流式调用失败：HTTP {resp.status_code} {error_text[:1500]}"
                )

            async for line in resp.aiter_lines():
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if not data_str:
                    continue
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                try:
                    choice = (data.get("choices") or [])[0]
                    delta = (choice.get("delta") or {}).get("content") or ""
                except Exception:
                    delta = ""

                if delta:
                    yield delta


async def generate_reply_with_memory(
    session_id: str,
    user_text: str,
    history_provider,
    append_chat_turn_func,
    user_message: dict | None = None,
) -> tuple[str, dict]:
    messages = await build_chat_messages(session_id, user_text, history_provider)
    assistant_text = await call_chat_model(messages)
    if user_message is None:
        user_message = make_user_message(user_text, input_type="text")
    session = await append_chat_turn_func(session_id, user_message, assistant_text)
    return assistant_text, session
