import json
import time
import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def make_session_id() -> str:
    return f"sess_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def make_message_id() -> str:
    return f"msg_{uuid.uuid4().hex}"


def make_audio_id() -> str:
    return f"aud_{uuid.uuid4().hex}"


def shorten_title(text: str, max_len: int = 26) -> str:
    text = (text or "").strip().replace("\n", " ")
    if not text:
        return "新对话"
    return text[:max_len] + ("…" if len(text) > max_len else "")


def make_message(role: str, text: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "role": role,
        "text": text,
        "createdAt": now_iso(),
    }


def make_user_message(
    text: str,
    input_type: str = "text",
    message_id: str | None = None,
    audio_id: str | None = None,
    audio_url: str | None = None,
) -> dict:
    msg = {
        "id": message_id or make_message_id(),
        "role": "user",
        "text": text,
        "inputType": input_type,
        "createdAt": now_iso(),
    }
    if audio_id:
        msg["audioId"] = audio_id
    if audio_url:
        msg["audioUrl"] = audio_url
    return msg


def make_session(session_id: str, title: str = "新对话") -> dict:
    ts = now_iso()
    return {
        "id": session_id,
        "title": title,
        "createdAt": ts,
        "updatedAt": ts,
        "messages": [],
    }


def ensure_ascii(name: str, value: str):
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise RuntimeError(f"{name} 含有非 ASCII 字符，请检查是否误填了中文占位文本。")
