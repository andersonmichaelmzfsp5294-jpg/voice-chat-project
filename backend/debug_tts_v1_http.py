import base64
import json
import os
import sys
import uuid
from pathlib import Path

import httpx

TEST_TEXT = "你好，我是一个测试语音。"
TTS_V1_URL = "https://openspeech.bytedance.com/api/v1/tts"
OUTPUT_DIR = Path(__file__).parent / "tmp_tts_test_v1"
OUTPUT_PATH = OUTPUT_DIR / "test.mp3"


def get_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing env: {name}")
    return value


def main() -> int:
    app_id = get_env("TTS_APP_ID")
    token = get_env("TTS_ACCESS_TOKEN")
    voice_type = get_env("TTS_VOICE_TYPE")

    headers = {
        "Authorization": f"Bearer;{token}",
        "Content-Type": "application/json",
    }

    reqid = uuid.uuid4().hex
    body = {
        "app": {
            "appid": app_id,
            "token": token,
            "cluster": "volcano_tts",
        },
        "user": {"uid": "debug-user"},
        "audio": {
            "voice_type": voice_type,
            "encoding": "mp3",
            "speed_ratio": 1.0,
        },
        "request": {
            "reqid": reqid,
            "text": TEST_TEXT,
            "operation": "query",
        },
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(TTS_V1_URL, headers=headers, json=body)
    except Exception as e:
        print(f"[error] request failed: {type(e).__name__}: {e}")
        return 1

    if resp.status_code != 200:
        print(f"[error] HTTP {resp.status_code}")
        print(resp.text)
        return 1

    try:
        payload = resp.json()
    except Exception:
        print("[error] response is not JSON")
        print(resp.text)
        return 1

    data_b64 = payload.get("data")
    if not data_b64:
        print("[error] response JSON has no data field")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    try:
        audio_bytes = base64.b64decode(data_b64)
    except Exception as e:
        print(f"[error] base64 decode failed: {type(e).__name__}: {e}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(audio_bytes)

    code = payload.get("code")
    message = payload.get("message")
    duration = payload.get("duration")
    size_bytes = OUTPUT_PATH.stat().st_size

    print(f"[ok] code={code} message={message} duration={duration} size_bytes={size_bytes}")
    print(f"[ok] saved: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
