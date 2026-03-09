import base64
import re
import json
import uuid
import time
import asyncio
import shutil
import subprocess
import gzip
from pathlib import Path
from datetime import datetime

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from models import TextChatRequest, TtsFullRequest
from storage_utils import (
    load_store,
    save_store,
    load_audio_registry,
    save_audio_registry,
)
from utils import (
    now_iso,
    sse_event,
    make_session_id,
    make_message_id,
    make_audio_id,
    shorten_title,
    make_message,
    make_user_message,
    make_session,
    ensure_ascii,
)

# =========================
# 环境变量
from config import (
    VOLC_APP_ID,
    VOLC_ACCESS_TOKEN,
    NGROK_PUBLIC_URL,
    ALLOW_ORIGINS,
    FFMPEG_BIN,
    ARK_API_KEY,
    ARK_MODEL,
    ARK_BASE_URL,
    ARK_TIMEOUT_SEC,
    ARK_MAX_TOKENS,
    TTS_APP_ID,
    TTS_ACCESS_TOKEN,
    TTS_RESOURCE_ID,
    TTS_VOICE_TYPE,
    TTS_UNI_URL,
    TTS_WS_RESOURCE_ID,
    TTS_WS_URL,
    TTS_ENCODING,
    TTS_UID,
    TTS_SEGMENT_HARD_LEN,
    TTS_SEGMENT_SOFT_MIN_LEN,
    TTS_SEGMENT_SOFT_WAIT_SEC,
    MAX_HISTORY_ROUNDS,
    ARK_SYSTEM_PROMPT,
    AUC_SUBMIT_URL,
    AUC_QUERY_URL,
    AUC_RESOURCE_ID,
    BASE_DIR,
    TMP_DIR,
    STORE_FILE,
    AUDIO_DIR,
    AUDIO_REGISTRY_FILE,
    TTS_SEGMENTS_DIR,
)

app = FastAPI(title="Voice Chat Backend (AUC + Ark + Session History)", version="0.6")

extra_origins = [o.strip() for o in ALLOW_ORIGINS.split(",") if o.strip()] if ALLOW_ORIGINS else []
allow_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    *extra_origins,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORE_LOCK = asyncio.Lock()


# =========================
# 工具函数：时间 / 存储
# =========================
async def append_audio_registry_item(item: dict):
    async with STORE_LOCK:
        data = load_audio_registry()
        items = data.setdefault("items", [])
        items.append(item)
        save_audio_registry(data)


async def list_sessions_meta() -> list[dict]:
    async with STORE_LOCK:
        data = load_store()
        sessions = list(data.get("sessions", {}).values())

    items = []
    for sess in sessions:
        messages = sess.get("messages", [])
        last_preview = ""
        if messages:
            last_preview = (messages[-1].get("text") or "").strip()

        items.append(
            {
                "id": sess["id"],
                "title": sess.get("title") or "新对话",
                "createdAt": sess.get("createdAt"),
                "updatedAt": sess.get("updatedAt"),
                "lastPreview": last_preview[:80],
            }
        )

    items.sort(key=lambda x: x.get("updatedAt") or "", reverse=True)
    return items


async def get_session_detail(session_id: str) -> dict | None:
    async with STORE_LOCK:
        data = load_store()
        return data.get("sessions", {}).get(session_id)


async def resolve_session_title(session_id: str, fallback_text: str) -> str:
    session = await get_session_detail(session_id)
    title = (session or {}).get("title") if session else None
    if title:
        return title
    return shorten_title(fallback_text) if fallback_text else "新对话"


async def delete_session_data(session_id: str) -> bool:
    async with STORE_LOCK:
        data = load_store()
        sessions = data.get("sessions", {})
        existed = session_id in sessions
        if existed:
            sessions.pop(session_id, None)
            save_store(data)
            registry = load_audio_registry()
            changed = False
            for item in registry.get("items", []):
                if item.get("sessionId") == session_id and not item.get("isOrphaned", False):
                    item["isOrphaned"] = True
                    changed = True
            if changed:
                save_audio_registry(registry)
        return existed


async def get_model_history(session_id: str) -> list[dict[str, str]]:
    session = await get_session_detail(session_id)
    if not session:
        return []

    raw_messages = session.get("messages", [])
    history = []
    for item in raw_messages[-MAX_HISTORY_ROUNDS * 2 :]:
        role = item.get("role")
        text = (item.get("text") or "").strip()
        if role in ("user", "assistant") and text:
            history.append({"role": role, "content": text})
    return history


async def append_chat_turn(session_id: str, user_message: dict, assistant_text: str) -> dict:
    async with STORE_LOCK:
        data = load_store()
        sessions = data.setdefault("sessions", {})

        session = sessions.get(session_id)
        if not session:
            session = make_session(
                session_id=session_id,
                title=shorten_title((user_message.get("text") or "").strip()),
            )
            sessions[session_id] = session

        if not session.get("title") or session.get("title") == "新对话":
            session["title"] = shorten_title((user_message.get("text") or "").strip())

        session.setdefault("messages", [])
        if not user_message.get("createdAt"):
            user_message["createdAt"] = now_iso()
        session["messages"].append(user_message)
        session["messages"].append(make_message("assistant", assistant_text))
        session["updatedAt"] = now_iso()

        save_store(data)
        return session


# =========================
# 基础接口
# =========================
@app.get("/health")
def health():
    data = load_store()
    return {
        "ok": True,
        "tmp_dir": str(TMP_DIR),
        "store_file": str(STORE_FILE),
        "session_count": len(data.get("sessions", {})),
        "has_auc_env": bool(VOLC_APP_ID and VOLC_ACCESS_TOKEN and NGROK_PUBLIC_URL),
        "has_chat_model": bool(ARK_API_KEY and ARK_MODEL and ARK_BASE_URL),
    }


@app.get("/download/{filename}")
def download_file(filename: str):
    """
    仅允许下载 tmp 目录中由后端生成的 wav 文件
    """
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")

    if not re.fullmatch(r"[a-f0-9\-]+\.wav", filename):
        raise HTTPException(status_code=400, detail="invalid wav filename")

    path = TMP_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(
        path=str(path),
        media_type="audio/wav",
        filename=filename,
    )


@app.get("/audio/{subpath:path}")
def get_audio_file(subpath: str):
    if ".." in subpath:
        raise HTTPException(status_code=400, detail="invalid path")

    full_path = (AUDIO_DIR / subpath).resolve()
    base_path = AUDIO_DIR.resolve()

    if base_path not in full_path.parents and full_path != base_path:
        raise HTTPException(status_code=400, detail="invalid path")

    if full_path.suffix.lower() != ".webm":
        raise HTTPException(status_code=400, detail="invalid audio type")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(
        path=str(full_path),
        media_type="audio/webm",
        filename=full_path.name,
    )


@app.get("/tts/{filename}")
def get_tts_segment(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="invalid filename")

    if not re.fullmatch(r"[A-Za-z0-9._-]+\.(mp3|wav)", filename):
        raise HTTPException(status_code=400, detail="invalid tts filename")

    path = TTS_SEGMENTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")

    media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=filename,
    )


@app.get("/sessions")
async def get_sessions():
    return {"items": await list_sessions_meta()}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = await get_session_detail(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = await delete_session_data(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True}


@app.get("/audio-registry")
def get_audio_registry():
    return load_audio_registry()

@app.post("/tts/full")
async def tts_full(payload: TtsFullRequest):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    try:
        audio_url = await synthesize_tts_v1_full_text(text)
        return {"audioUrl": audio_url}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"未处理异常: {str(e)}")



# =========================
# 工具函数：AUC / Ark / ffmpeg
# =========================
def require_auc_env():
    missing = []

    if not VOLC_APP_ID:
        missing.append("VOLC_APP_ID")
    if not VOLC_ACCESS_TOKEN:
        missing.append("VOLC_ACCESS_TOKEN")
    if not NGROK_PUBLIC_URL:
        missing.append("NGROK_PUBLIC_URL")

    if missing:
        raise RuntimeError(f"缺少 AUC 环境变量：{', '.join(missing)}")


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


def has_tts_env() -> bool:
    return bool(
        TTS_APP_ID and TTS_ACCESS_TOKEN and TTS_VOICE_TYPE and TTS_RESOURCE_ID and TTS_UNI_URL
    )


def require_tts_env():
    missing = []
    if not TTS_APP_ID:
        missing.append("TTS_APP_ID")
    if not TTS_ACCESS_TOKEN:
        missing.append("TTS_ACCESS_TOKEN")
    if not TTS_VOICE_TYPE:
        missing.append("TTS_VOICE_TYPE")
    if not TTS_RESOURCE_ID:
        missing.append("TTS_RESOURCE_ID")
    if not TTS_UNI_URL:
        missing.append("TTS_UNI_URL")
    if missing:
        raise RuntimeError("TTS V1 缺少环境变量: " + ", ".join(missing))

def require_tts_v1_env():
    missing = []
    if not TTS_APP_ID:
        missing.append("TTS_APP_ID")
    if not TTS_ACCESS_TOKEN:
        missing.append("TTS_ACCESS_TOKEN")
    if not TTS_VOICE_TYPE:
        missing.append("TTS_VOICE_TYPE")
    if missing:
        raise RuntimeError("TTS V1 缺少环境变量: " + ", ".join(missing))



def ensure_ascii(name: str, value: str):
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        raise RuntimeError(f"{name} 含有非 ASCII 字符，请检查是否误填了中文占位文本。")


def ensure_ffmpeg():
    if shutil.which(FFMPEG_BIN) is None and not Path(FFMPEG_BIN).exists():
        raise RuntimeError(
            "未检测到 ffmpeg：请先安装并确保 ffmpeg 在 PATH 中，"
            "或者设置 FFMPEG_BIN，例如 C:\\ffmpeg\\bin\\ffmpeg.exe"
        )


def convert_webm_to_wav(webm_path: Path, wav_path: Path):
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i",
        str(webm_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码失败：{proc.stderr[:4000]}")


async def auc_submit_and_query(audio_url: str, language: str | None = None):
    ensure_ascii("VOLC_APP_ID", VOLC_APP_ID)
    ensure_ascii("VOLC_ACCESS_TOKEN", VOLC_ACCESS_TOKEN)
    ensure_ascii("AUC_RESOURCE_ID", AUC_RESOURCE_ID)

    if not VOLC_APP_ID.isdigit():
        raise RuntimeError("VOLC_APP_ID 应该是纯数字 APPID，不是实例名。")

    request_id = str(uuid.uuid4())

    headers_submit = {
        "Content-Type": "application/json",
        "X-Api-App-Key": VOLC_APP_ID,
        "X-Api-Access-Key": VOLC_ACCESS_TOKEN,
        "X-Api-Resource-Id": AUC_RESOURCE_ID,
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }

    body = {
        "user": {"uid": "wayfarer"},
        "audio": {
            "format": "wav",
            "url": audio_url,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": False,
            "show_utterances": False,
        },
    }

    if language:
        body["audio"]["language"] = language

    async with httpx.AsyncClient(timeout=30) as client:
        submit_resp = await client.post(AUC_SUBMIT_URL, headers=headers_submit, json=body)

        submit_code = submit_resp.headers.get("X-Api-Status-Code")
        submit_msg = submit_resp.headers.get("X-Api-Message")
        submit_logid = submit_resp.headers.get("X-Tt-Logid")

        if submit_code != "20000000":
            raise RuntimeError(
                f"AUC submit 失败：code={submit_code}, msg={submit_msg}, logid={submit_logid}"
            )

        headers_query = {
            "Content-Type": "application/json",
            "X-Api-App-Key": VOLC_APP_ID,
            "X-Api-Access-Key": VOLC_ACCESS_TOKEN,
            "X-Api-Resource-Id": AUC_RESOURCE_ID,
            "X-Api-Request-Id": request_id,
        }

        for _ in range(60):
            query_resp = await client.post(AUC_QUERY_URL, headers=headers_query, json={})

            qcode = query_resp.headers.get("X-Api-Status-Code")
            qmsg = query_resp.headers.get("X-Api-Message")
            qlogid = query_resp.headers.get("X-Tt-Logid")

            if qcode == "20000000":
                data = query_resp.json()
                text = (data.get("result") or {}).get("text", "")
                return text, {
                    "requestId": request_id,
                    "logid": qlogid,
                    "raw": data,
                }

            if qcode in ("20000001", "20000002"):
                await asyncio.sleep(1.0)
                continue

            raise RuntimeError(
                f"AUC query 失败：code={qcode}, msg={qmsg}, logid={qlogid}"
            )

        raise RuntimeError("AUC query 超时：超过轮询次数仍未完成。")


async def build_chat_messages(session_id: str, user_text: str) -> list[dict[str, str]]:
    history = await get_model_history(session_id)
    return [
        {"role": "system", "content": ARK_SYSTEM_PROMPT},
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


def build_tts_request_bytes(text: str, reqid: str) -> bytes:
    request_json = {
        "app": {
            "appid": TTS_APP_ID,
            "token": TTS_ACCESS_TOKEN,
            "cluster": "volcano_tts",
        },
        "user": {"uid": TTS_UID},
        "audio": {
            "voice_type": TTS_VOICE_TYPE,
            "encoding": TTS_ENCODING,
        },
        "request": {
            "reqid": reqid,
            "text": text,
            "text_type": "plain",
            "operation": "submit",
        },
    }

    payload = json.dumps(request_json).encode("utf-8")
    payload = gzip.compress(payload)

    header = bytearray(b"\x11\x10\x11\x00")
    header.extend(len(payload).to_bytes(4, "big"))
    header.extend(payload)
    return bytes(header)


def parse_tts_response_bytes(chunk: bytes) -> tuple[bool, bytes | None]:
    if len(chunk) < 4:
        return False, None

    header_size = chunk[0] & 0x0F
    message_type = chunk[1] >> 4
    message_flags = chunk[1] & 0x0F
    compression = chunk[2] & 0x0F
    payload = chunk[header_size * 4 :]

    if message_type == 0xF:
        if len(payload) < 8:
            raise RuntimeError("TTS 返回错误：响应过短")
        error_code = int.from_bytes(payload[:4], "big")
        error_size = int.from_bytes(payload[4:8], "big")
        error_msg = payload[8 : 8 + error_size]
        if compression == 1:
            error_msg = gzip.decompress(error_msg)
        raise RuntimeError(f"TTS 错误：code={error_code}, msg={error_msg.decode('utf-8', 'ignore')}")

    if message_type == 0xB:
        if message_flags == 0 or len(payload) < 8:
            return False, None
        seq = int.from_bytes(payload[:4], "big", signed=True)
        size = int.from_bytes(payload[4:8], "big")
        audio = payload[8 : 8 + size]
        done = seq < 0
        return done, audio

    return False, None


_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]+$")


def _looks_like_base64(value: str) -> bool:
    if len(value) < 16:
        return False
    if not _BASE64_RE.match(value):
        return False
    mod = len(value) % 4
    return mod in (0, 2, 3)


def _extract_audio_b64(payload) -> str | None:
    if isinstance(payload, dict):
        for key in ("audio", "audio_data", "audioData", "data"):
            if key in payload:
                val = payload[key]
                if isinstance(val, str) and _looks_like_base64(val):
                    return val
                found = _extract_audio_b64(val)
                if found:
                    return found
        for val in payload.values():
            found = _extract_audio_b64(val)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_audio_b64(item)
            if found:
                return found
    return None


def pop_tts_segment(buffer: str, force_soft: bool) -> tuple[str | None, str]:
    if not buffer:
        return None, buffer

    punctuations = "。！？；\n"
    last_punc = -1
    for i in range(len(buffer) - 1, -1, -1):
        if buffer[i] in punctuations:
            last_punc = i
            break

    if last_punc >= 0:
        segment = buffer[: last_punc + 1].strip()
        rest = buffer[last_punc + 1 :]
        if segment:
            return segment, rest

    if len(buffer) >= TTS_SEGMENT_HARD_LEN:
        segment = buffer[:TTS_SEGMENT_HARD_LEN].strip()
        rest = buffer[TTS_SEGMENT_HARD_LEN :]
        return segment, rest

    if force_soft and len(buffer) >= TTS_SEGMENT_SOFT_MIN_LEN:
        return buffer.strip(), ""

    return None, buffer


async def synthesize_tts_segment_bidirectional(text: str, output_path: Path):
    require_tts_env()
    try:
        import websockets
    except Exception as e:
        raise RuntimeError(f"缺少 websockets 依赖：{e}")

    reqid = uuid.uuid4().hex
    headers = {
        "Authorization": f"Bearer;{TTS_ACCESS_TOKEN}",
        "Resource-Id": TTS_WS_RESOURCE_ID,
    }
    request_bytes = build_tts_request_bytes(text, reqid)

    try:
        async with websockets.connect(
            TTS_WS_URL, additional_headers=headers, ping_interval=None
        ) as ws:
            await ws.send(request_bytes)
            with output_path.open("wb") as f:
                while True:
                    resp = await ws.recv()
                    if isinstance(resp, str):
                        continue
                    done, audio = parse_tts_response_bytes(resp)
                    if audio:
                        f.write(audio)
                    if done:
                        break
    except Exception:
        print(
            "TTS ws connect failed: "
            f"url={TTS_WS_URL} "
            f"resource_id={TTS_WS_RESOURCE_ID} "
            "operation=submit "
            f"voice_type={TTS_VOICE_TYPE}"
        )
        raise


async def synthesize_tts_segment(text: str, output_path: Path):
    require_tts_env()
    reqid = uuid.uuid4().hex
    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": TTS_APP_ID,
        "X-Api-Access-Key": TTS_ACCESS_TOKEN,
        "X-Api-Resource-Id": TTS_RESOURCE_ID,
        "X-Api-Request-Id": reqid,
    }

    body = {
        "user": {"uid": TTS_UID},
        "req_params": {
            "text": text,
            "text_type": "plain",
            "voice_type": TTS_VOICE_TYPE,
            "encoding": TTS_ENCODING,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=ARK_TIMEOUT_SEC) as client:
            async def fetch_chunked(url: str):
                got_audio_chunked = False
                text_snippet = ""
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    status = resp.status_code
                    content_type = resp.headers.get("content-type", "")
                    if status != 200:
                        error_text = (await resp.aread())[:1500]
                        return False, status, content_type, error_text.decode("utf-8", "ignore")

                    is_textual = content_type.startswith("text/") or "json" in content_type
                    with output_path.open("wb") as f:
                        async for chunk in resp.aiter_bytes():
                            if chunk:
                                f.write(chunk)
                                got_audio_chunked = True
                                if is_textual and len(text_snippet) < 1000:
                                    text_snippet += chunk.decode("utf-8", "ignore")
                                    if len(text_snippet) > 1000:
                                        text_snippet = text_snippet[:1000]
                return got_audio_chunked, status, content_type, text_snippet

            async with client.stream(
                "POST",
                TTS_UNI_URL,
                headers=headers,
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    error_text = (await resp.aread())[:1500]
                    print(
                        "TTS uni failed: "
                        f"url={TTS_UNI_URL} "
                        f"resource_id={TTS_RESOURCE_ID} "
                        f"voice_type={TTS_VOICE_TYPE} "
                        f"status={resp.status_code} "
                        f"error={error_text.decode('utf-8', 'ignore')}"
                    )
                    raise RuntimeError(f"TTS uni HTTP {resp.status_code}")

                status = resp.status_code
                content_type = resp.headers.get("content-type", "")
                is_sse = "text/event-stream" in content_type or TTS_UNI_URL.endswith("/sse")
                got_audio = False
                debug_sse_lines: list[str] = []
                debug_text_snippet = ""

                with output_path.open("wb") as f:
                    if is_sse:
                        async for line in resp.aiter_lines():
                            if line and (line.startswith("data:") or line.startswith("event:")):
                                if len(debug_sse_lines) < 10:
                                    debug_sse_lines.append(line)
                            if not line:
                                continue
                            if not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if not data_str or data_str == "[DONE]":
                                continue
                            try:
                                payload = json.loads(data_str)
                            except Exception:
                                continue
                            audio_b64 = _extract_audio_b64(payload)
                            if audio_b64:
                                try:
                                    audio_bytes = base64.b64decode(audio_b64)
                                except Exception:
                                    continue
                                f.write(audio_bytes)
                                got_audio = True
                    else:
                        is_textual = content_type.startswith("text/") or "json" in content_type
                        async for chunk in resp.aiter_bytes():
                            if chunk:
                                f.write(chunk)
                                got_audio = True
                                if is_textual and len(debug_text_snippet) < 1000:
                                    debug_text_snippet += chunk.decode("utf-8", "ignore")
                                    if len(debug_text_snippet) > 1000:
                                        debug_text_snippet = debug_text_snippet[:1000]

                if not got_audio:
                    print(
                        "TTS uni warning: no audio bytes received "
                        f"url={TTS_UNI_URL} resource_id={TTS_RESOURCE_ID} "
                        f"voice_type={TTS_VOICE_TYPE} status={status} content_type={content_type}"
                    )
                    if is_sse:
                        if debug_sse_lines:
                            print("TTS uni sse sample (first 10 lines):")
                            for item in debug_sse_lines:
                                print(f"  {item}")
                        chunked_url = (
                            TTS_UNI_URL[:-4] if TTS_UNI_URL.endswith("/sse") else TTS_UNI_URL
                        )
                        got_audio_chunked, c_status, c_type, c_text = await fetch_chunked(
                            chunked_url
                        )
                        if got_audio_chunked:
                            return
                        print(
                            "TTS uni chunked fallback no audio "
                            f"url={chunked_url} status={c_status} content_type={c_type}"
                        )
                        if c_text:
                            print("TTS uni chunked text sample:")
                            print(c_text)
                    else:
                        if debug_text_snippet:
                            print("TTS uni text sample:")
                            print(debug_text_snippet)
    except Exception as e:
        print(
            "TTS uni exception: "
            f"url={TTS_UNI_URL} "
            f"resource_id={TTS_RESOURCE_ID} "
            f"voice_type={TTS_VOICE_TYPE} "
            f"error={type(e).__name__}: {e}"
        )
        raise


async def synthesize_tts_v1_full_text(text: str) -> str:
    require_tts_v1_env()
    reqid = uuid.uuid4().hex
    headers = {
        "Authorization": f"Bearer;{TTS_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "app": {
            "appid": TTS_APP_ID,
            "token": TTS_ACCESS_TOKEN,
            "cluster": "volcano_tts",
        },
        "user": {"uid": "debug-user"},
        "audio": {
            "voice_type": TTS_VOICE_TYPE,
            "encoding": "mp3",
            "speed_ratio": 1.0,
        },
        "request": {
            "reqid": reqid,
            "text": text,
            "operation": "query",
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post("https://openspeech.bytedance.com/api/v1/tts", headers=headers, json=body)

    if resp.status_code != 200:
        print(f"TTS v1 failed: status={resp.status_code}")
        print(resp.text[:2000])
        raise RuntimeError(f"TTS v1 HTTP {resp.status_code}")

    try:
        payload = resp.json()
    except Exception:
        print("TTS v1 response not JSON")
        print(resp.text[:2000])
        raise RuntimeError("TTS v1 invalid response")

    data_b64 = payload.get("data")
    if not data_b64:
        print("TTS v1 response missing data")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
        raise RuntimeError("TTS v1 missing data")

    try:
        audio_bytes = base64.b64decode(data_b64)
    except Exception as e:
        print(f"TTS v1 base64 decode failed: {type(e).__name__}: {e}")
        raise RuntimeError("TTS v1 decode failed")

    filename = f"tts_full_{reqid}.mp3"
    output_path = TTS_SEGMENTS_DIR / filename
    output_path.write_bytes(audio_bytes)
    return f"/tts/{filename}"


async def generate_reply_with_memory(
    session_id: str,
    user_text: str,
    user_message: dict | None = None,
) -> tuple[str, dict]:
    messages = await build_chat_messages(session_id, user_text)
    assistant_text = await call_chat_model(messages)
    if user_message is None:
        user_message = make_user_message(user_text, input_type="text")
    session = await append_chat_turn(session_id, user_message, assistant_text)
    return assistant_text, session


# =========================
# 主业务接口
# =========================
@app.post("/chat/text")
async def chat_text(payload: TextChatRequest):
    user_text = (payload.text or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text is required")

    sid = payload.sessionId or make_session_id()
    rid = str(uuid.uuid4())

    try:
        assistant_text, session = await generate_reply_with_memory(
            session_id=sid,
            user_text=user_text,
        )

        return {
            "requestId": rid,
            "sessionId": sid,
            "sessionTitle": session.get("title", "新对话"),
            "userText": user_text,
            "assistantText": assistant_text,
            "debug": {
                "ark_model": ARK_MODEL,
                "history_rounds": len(session.get("messages", [])) // 2,
            },
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"未处理异常：{str(e)}")


@app.post("/chat/text/stream")
async def chat_text_stream(payload: TextChatRequest):
    user_text = (payload.text or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text is required")

    sid = payload.sessionId or make_session_id()
    session_title = await resolve_session_title(sid, user_text)
    user_message = make_user_message(user_text, input_type="text")

    async def event_stream():
        assistant_parts: list[str] = []
        try:
            yield sse_event(
                {
                    "type": "start",
                    "sessionId": sid,
                    "sessionTitle": session_title,
                    "transcript": user_text,
                }
            )

            messages = await build_chat_messages(sid, user_text)
            async for delta in iter_ark_stream(messages):
                assistant_parts.append(delta)
                yield sse_event({"type": "delta", "content": delta})

            assistant_text = "".join(assistant_parts).strip()
            session = await append_chat_turn(sid, user_message, assistant_text)

            yield sse_event({"type": "done"})
        except Exception as e:
            yield sse_event({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/text/stream-tts")
async def chat_text_stream_tts(payload: TextChatRequest):
    user_text = (payload.text or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="text is required")

    sid = payload.sessionId or make_session_id()
    session_title = await resolve_session_title(sid, user_text)
    user_message = make_user_message(user_text, input_type="text")

    async def event_stream():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        tts_enabled = has_tts_env()
        if tts_enabled:
            try:
                import websockets  # noqa: F401
            except Exception as e:
                print(f"TTS disabled: {e}")
                tts_enabled = False

        async def tts_task(segment_text: str, index: int):
            if not tts_enabled:
                return
            ext = "mp3" if TTS_ENCODING.lower() == "mp3" else "wav"
            filename = f"tts_{sid}_{index}_{uuid.uuid4().hex}.{ext}"
            output_path = TTS_SEGMENTS_DIR / filename
            try:
                await synthesize_tts_segment(segment_text, output_path)
                await queue.put(
                    {
                        "type": "audio_segment",
                        "segmentId": f"seg_{index:03d}",
                        "audioUrl": f"/tts/{filename}",
                        "index": index,
                    }
                )
            except Exception as e:
                print(f"TTS segment failed: {e}")

        async def producer():
            assistant_parts: list[str] = []
            tts_tasks: list[asyncio.Task] = []
            tts_buffer = ""
            tts_index = 0
            tts_lock = asyncio.Lock()
            tts_event = asyncio.Event()

            def flush_tts_buffer(force_soft: bool):
                nonlocal tts_buffer, tts_index
                segment, tts_buffer = pop_tts_segment(tts_buffer, force_soft)
                while segment:
                    tts_index += 1
                    tts_tasks.append(asyncio.create_task(tts_task(segment, tts_index)))
                    segment, tts_buffer = pop_tts_segment(tts_buffer, False)

            async def soft_flush_loop():
                try:
                    while True:
                        try:
                            await asyncio.wait_for(
                                tts_event.wait(), timeout=TTS_SEGMENT_SOFT_WAIT_SEC
                            )
                            tts_event.clear()
                        except asyncio.TimeoutError:
                            async with tts_lock:
                                if tts_buffer:
                                    flush_tts_buffer(True)
                except asyncio.CancelledError:
                    return

            soft_flush_task = None
            if tts_enabled:
                soft_flush_task = asyncio.create_task(soft_flush_loop())

            try:
                await queue.put(
                    {
                        "type": "start",
                        "sessionId": sid,
                        "sessionTitle": session_title,
                        "transcript": user_text,
                    }
                )

                messages = await build_chat_messages(sid, user_text)
                async for delta in iter_ark_stream(messages):
                    assistant_parts.append(delta)
                    await queue.put({"type": "delta", "content": delta})

                    if tts_enabled:
                        async with tts_lock:
                            tts_buffer += delta
                            tts_event.set()
                            flush_tts_buffer(False)

                if tts_enabled:
                    async with tts_lock:
                        if tts_buffer.strip():
                            flush_tts_buffer(True)
                    if soft_flush_task:
                        soft_flush_task.cancel()
                        try:
                            await soft_flush_task
                        except asyncio.CancelledError:
                            pass

                assistant_text = "".join(assistant_parts).strip()
                await append_chat_turn(sid, user_message, assistant_text)

                if tts_tasks:
                    await asyncio.gather(*tts_tasks, return_exceptions=True)

                await queue.put({"type": "audio_done"})
                await queue.put({"type": "done"})
            except Exception as e:
                await queue.put({"type": "error", "message": str(e)})
            finally:
                if soft_flush_task:
                    soft_flush_task.cancel()
                await queue.put(None)

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield sse_event(item)
        finally:
            producer_task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/audio")
async def chat_audio(
    audio: UploadFile = File(...),
    sessionId: str | None = Form(default=None),
    deviceLabel: str | None = Form(default=None),
):
    require_auc_env()
    require_ark_env()
    ensure_ffmpeg()

    sid = sessionId or make_session_id()
    rid = str(uuid.uuid4())
    message_id = make_message_id()
    audio_id = make_audio_id()

    date_path = datetime.now().strftime("%Y/%m/%d")
    audio_session_dir = AUDIO_DIR / date_path / sid
    audio_session_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{message_id}.webm"
    stored_path = audio_session_dir / stored_filename

    webm_path = TMP_DIR / f"{rid}.webm"
    wav_path = TMP_DIR / f"{rid}.wav"

    try:
        data = await audio.read()
        stored_path.write_bytes(data)
        webm_path.write_bytes(data)

        convert_webm_to_wav(webm_path, wav_path)

        public_wav_url = f"{NGROK_PUBLIC_URL}/download/{wav_path.name}"
        public_audio_url = f"/audio/{stored_path.relative_to(AUDIO_DIR).as_posix()}"

        final_text, asr_debug = await auc_submit_and_query(public_wav_url)
        final_text = (final_text or "").strip()
        if not final_text:
            final_text = "（未识别到清晰语音）"

        user_message = make_user_message(
            final_text,
            input_type="audio",
            message_id=message_id,
            audio_id=audio_id,
            audio_url=public_audio_url,
        )

        assistant_text, session = await generate_reply_with_memory(
            session_id=sid,
            user_text=final_text,
            user_message=user_message,
        )

        await append_audio_registry_item(
            {
                "audioId": audio_id,
                "sessionId": sid,
                "messageId": message_id,
                "sessionTitle": session.get("title", "新对话"),
                "inputType": "audio",
                "originalFilename": audio.filename or "recording.webm",
                "storedFilename": stored_filename,
                "storedPath": stored_path.relative_to(BASE_DIR).as_posix(),
                "publicUrl": public_audio_url,
                "contentType": audio.content_type or "audio/webm",
                "sizeBytes": stored_path.stat().st_size if stored_path.exists() else 0,
                "transcript": final_text,
                "assistantReply": assistant_text,
                "createdAt": now_iso(),
                "isOrphaned": False,
            }
        )

        return {
            "requestId": rid,
            "sessionId": sid,
            "sessionTitle": session.get("title", "新对话"),
            "transcript": final_text,
            "assistantText": assistant_text,
            "debug": {
                "upload_content_type": audio.content_type,
                "webm_file": webm_path.name,
                "wav_file": wav_path.name,
                "public_wav_url": public_wav_url,
                "deviceLabel": deviceLabel,
                "asr": asr_debug,
                "ark_model": ARK_MODEL,
                "history_rounds": len(session.get("messages", [])) // 2,
            },
        }

    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"未处理异常：{str(e)}")
    finally:
        if webm_path.exists():
            webm_path.unlink(missing_ok=True)
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)


@app.post("/chat/audio/stream")
async def chat_audio_stream(
    audio: UploadFile = File(...),
    sessionId: str | None = Form(default=None),
    deviceLabel: str | None = Form(default=None),
):
    sid = sessionId or make_session_id()
    rid = str(uuid.uuid4())
    message_id = make_message_id()
    audio_id = make_audio_id()

    date_path = datetime.now().strftime("%Y/%m/%d")
    audio_session_dir = AUDIO_DIR / date_path / sid
    audio_session_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{message_id}.webm"
    stored_path = audio_session_dir / stored_filename

    webm_path = TMP_DIR / f"{rid}.webm"
    wav_path = TMP_DIR / f"{rid}.wav"

    async def event_stream():
        assistant_parts: list[str] = []
        try:
            require_auc_env()
            require_ark_env()
            ensure_ffmpeg()

            data = await audio.read()
            stored_path.write_bytes(data)
            webm_path.write_bytes(data)

            convert_webm_to_wav(webm_path, wav_path)

            public_wav_url = f"{NGROK_PUBLIC_URL}/download/{wav_path.name}"
            public_audio_url = f"/audio/{stored_path.relative_to(AUDIO_DIR).as_posix()}"

            final_text, asr_debug = await auc_submit_and_query(public_wav_url)
            final_text = (final_text or "").strip()
            if not final_text:
                final_text = "（未识别到清晰语音）"

            session_title = await resolve_session_title(sid, final_text)

            yield sse_event(
                {
                    "type": "start",
                    "sessionId": sid,
                    "sessionTitle": session_title,
                    "transcript": final_text,
                }
            )

            messages = await build_chat_messages(sid, final_text)
            async for delta in iter_ark_stream(messages):
                assistant_parts.append(delta)
                yield sse_event({"type": "delta", "content": delta})

            assistant_text = "".join(assistant_parts).strip()

            user_message = make_user_message(
                final_text,
                input_type="audio",
                message_id=message_id,
                audio_id=audio_id,
                audio_url=public_audio_url,
            )

            session = await append_chat_turn(sid, user_message, assistant_text)

            await append_audio_registry_item(
                {
                    "audioId": audio_id,
                    "sessionId": sid,
                    "messageId": message_id,
                    "sessionTitle": session.get("title", "新对话"),
                    "inputType": "audio",
                    "originalFilename": audio.filename or "recording.webm",
                    "storedFilename": stored_filename,
                    "storedPath": stored_path.relative_to(BASE_DIR).as_posix(),
                    "publicUrl": public_audio_url,
                    "contentType": audio.content_type or "audio/webm",
                    "sizeBytes": stored_path.stat().st_size if stored_path.exists() else 0,
                    "transcript": final_text,
                    "assistantReply": assistant_text,
                    "createdAt": now_iso(),
                    "isOrphaned": False,
                }
            )

            yield sse_event({"type": "done"})
        except Exception as e:
            yield sse_event({"type": "error", "message": str(e)})
        finally:
            if webm_path.exists():
                webm_path.unlink(missing_ok=True)
            if wav_path.exists():
                wav_path.unlink(missing_ok=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
