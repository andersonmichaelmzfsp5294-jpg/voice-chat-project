import base64
import json
import re
import uuid

import httpx

from config import (
    ARK_TIMEOUT_SEC,
    TTS_APP_ID,
    TTS_ACCESS_TOKEN,
    TTS_ENCODING,
    TTS_RESOURCE_ID,
    TTS_SEGMENT_HARD_LEN,
    TTS_SEGMENT_SOFT_MIN_LEN,
    TTS_UNI_URL,
    TTS_UID,
    TTS_VOICE_TYPE,
    TTS_SEGMENTS_DIR,
)


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


async def synthesize_tts_segment(text: str, output_path):
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
        resp = await client.post(
            "https://openspeech.bytedance.com/api/v1/tts", headers=headers, json=body
        )

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
