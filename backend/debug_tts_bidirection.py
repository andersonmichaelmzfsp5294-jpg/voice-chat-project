import asyncio
import gzip
import importlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

TEST_TEXT = "你好，我是一个测试语音。"

DEFAULT_WS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
DEFAULT_CLUSTER = "volcano_tts"
DEFAULT_ENCODING = "mp3"


def get_env(name: str, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"missing env: {name}")
    return value


def build_tts_request_bytes(
    *,
    app_id: str,
    token: str,
    cluster: str,
    voice_type: str,
    encoding: str,
    text: str,
    reqid: str,
    operation: str,
) -> bytes:
    request_json = {
        "app": {
            "appid": app_id,
            "token": token,
            "cluster": cluster,
        },
        "user": {"uid": "debug_tts"},
        "audio": {
            "voice_type": voice_type,
            "encoding": encoding,
        },
        "request": {
            "reqid": reqid,
            "text": text,
            "text_type": "plain",
            "operation": operation,
        },
    }

    payload = json.dumps(request_json, ensure_ascii=False).encode("utf-8")
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
            raise RuntimeError("TTS error: response too short")
        error_code = int.from_bytes(payload[:4], "big")
        error_size = int.from_bytes(payload[4:8], "big")
        error_msg = payload[8 : 8 + error_size]
        if compression == 1:
            error_msg = gzip.decompress(error_msg)
        raise RuntimeError(
            f"TTS error: code={error_code}, msg={error_msg.decode('utf-8', 'ignore')}"
        )

    if message_type == 0xB:
        if message_flags == 0 or len(payload) < 8:
            return False, None
        seq = int.from_bytes(payload[:4], "big", signed=True)
        size = int.from_bytes(payload[4:8], "big")
        audio = payload[8 : 8 + size]
        done = seq < 0
        return done, audio

    return False, None


def try_official_sdk() -> bool:
    candidates = [
        ("volcengine", None),
        ("volcengine.speech", None),
        ("volcengine.tts", None),
    ]
    for module_name, _ in candidates:
        try:
            importlib.import_module(module_name)
            print(f"[sdk] detected module: {module_name}")
            print("[sdk] no bidirectional TTS helper detected, falling back to raw WS.")
            return False
        except Exception:
            continue
    print("[sdk] official SDK not available, using raw WS.")
    return False


async def run_handshake_matrix():
    app_id = get_env("TTS_APP_ID")
    token = get_env("TTS_ACCESS_TOKEN")
    resource_id = get_env("TTS_RESOURCE_ID")
    voice_type = get_env("TTS_VOICE_TYPE")
    ws_url = get_env("TTS_WS_URL", required=False, default=DEFAULT_WS_URL)

    cluster = DEFAULT_CLUSTER
    encoding = DEFAULT_ENCODING

    print(f"[config] ws_url: {ws_url}")
    print(f"[config] resource_id(header): {resource_id}")
    print(f"[config] voice_type: {voice_type}")
    print(f"[config] app.cluster: {cluster}")
    print(f"[config] encoding: {encoding}")

    try:
        import websockets
    except Exception as e:
        raise RuntimeError(f"missing dependency: websockets ({e})")

    token_mask = token[:6] + ("..." if len(token) > 6 else "")
    cases = [
        (
            "A1",
            {
                "Authorization": f"Bearer;{token}",
                "Resource-Id": resource_id,
            },
            f"Bearer;{token_mask}",
        ),
        (
            "A2",
            {
                "Authorization": f"Bearer; {token}",
                "Resource-Id": resource_id,
            },
            f"Bearer; {token_mask}",
        ),
        (
            "A3",
            {
                "Authorization": f"Bearer {token}",
                "Resource-Id": resource_id,
            },
            f"Bearer {token_mask}",
        ),
        (
            "B1",
            {
                "Authorization": f"Bearer;{token}",
                "X-Api-Resource-Id": resource_id,
            },
            f"Bearer;{token_mask}",
        ),
        (
            "B2",
            {
                "Authorization": f"Bearer; {token}",
                "X-Api-Resource-Id": resource_id,
            },
            f"Bearer; {token_mask}",
        ),
        (
            "B3",
            {
                "Authorization": f"Bearer {token}",
                "X-Api-Resource-Id": resource_id,
            },
            f"Bearer {token_mask}",
        ),
    ]

    output_dir = Path(__file__).parent / "tmp_tts_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    def log_ws_error(case_name: str, err: Exception):
        print(f"[case {case_name}] handshake failed: {type(err).__name__}: {err}")
        exc_mod = sys.modules.get("websockets.exceptions")
        if exc_mod:
            invalid_status = getattr(exc_mod, "InvalidStatusCode", None)
            if invalid_status and isinstance(err, invalid_status):
                status = getattr(err, "status_code", None)
                headers = getattr(err, "headers", None)
                print(f"[case {case_name}] ws status: {status}")
                if headers:
                    print(f"[case {case_name}] ws headers: {headers}")

    success = False

    for case_name, headers, auth_display in cases:
        header_names = ", ".join(headers.keys())
        print(f"[case {case_name}] headers: {header_names}")
        print(f"[case {case_name}] authorization: {auth_display}")

        connected = False
        sent_start = False
        sent_submit = False
        sent_finish = False
        got_audio = False

        try:
            async with websockets.connect(
                ws_url, additional_headers=headers, ping_interval=None
            ) as ws:
                connected = True
                print(f"[case {case_name}] handshake ok")

                reqid = uuid.uuid4().hex
                filename = f"tts_test_{case_name}_{int(time.time())}_{uuid.uuid4().hex}.{encoding}"
                output_path = output_dir / filename

                print(f"[case {case_name}] start -> send")
                await ws.send(
                    build_tts_request_bytes(
                        app_id=app_id,
                        token=token,
                        cluster=cluster,
                        voice_type=voice_type,
                        encoding=encoding,
                        text="",
                        reqid=reqid,
                        operation="start",
                    )
                )
                sent_start = True
                print(f"[case {case_name}] start -> sent")

                print(f"[case {case_name}] submit -> send")
                await ws.send(
                    build_tts_request_bytes(
                        app_id=app_id,
                        token=token,
                        cluster=cluster,
                        voice_type=voice_type,
                        encoding=encoding,
                        text=TEST_TEXT,
                        reqid=reqid,
                        operation="submit",
                    )
                )
                sent_submit = True
                print(f"[case {case_name}] submit -> sent")

                print(f"[case {case_name}] finish -> send")
                await ws.send(
                    build_tts_request_bytes(
                        app_id=app_id,
                        token=token,
                        cluster=cluster,
                        voice_type=voice_type,
                        encoding=encoding,
                        text="",
                        reqid=reqid,
                        operation="finish",
                    )
                )
                sent_finish = True
                print(f"[case {case_name}] finish -> sent")

                with output_path.open("wb") as f:
                    while True:
                        resp = await ws.recv()
                        if isinstance(resp, str):
                            print(f"[case {case_name}] recv text: {resp[:200]}")
                            continue
                        done, audio = parse_tts_response_bytes(resp)
                        if audio:
                            got_audio = True
                            f.write(audio)
                        if done:
                            break

                print(f"[case {case_name}] connected:", "yes" if connected else "no")
                print(f"[case {case_name}] sent start:", "yes" if sent_start else "no")
                print(f"[case {case_name}] sent submit:", "yes" if sent_submit else "no")
                print(f"[case {case_name}] sent finish:", "yes" if sent_finish else "no")
                print(f"[case {case_name}] received audio:", "yes" if got_audio else "no")

                if got_audio:
                    print(f"[case {case_name}] saved: {output_path}")
                else:
                    if output_path.exists():
                        output_path.unlink(missing_ok=True)
                    print(f"[case {case_name}] no audio received; output file removed")

                print(f"[case {case_name}] success; stop further tests")
                success = True
                break
        except Exception as e:
            log_ws_error(case_name, e)
            continue

    if not success:
        print("[summary] all handshake combinations failed")
        print("[summary] likely service capability or permission issue, not body params")


async def main():
    try_official_sdk()
    await run_handshake_matrix()


if __name__ == "__main__":
    asyncio.run(main())
