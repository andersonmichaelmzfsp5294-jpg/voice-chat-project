import shutil
import subprocess
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from config import (
    VOLC_APP_ID,
    VOLC_ACCESS_TOKEN,
    NGROK_PUBLIC_URL,
    FFMPEG_BIN,
    AUC_SUBMIT_URL,
    AUC_QUERY_URL,
    AUC_RESOURCE_ID,
    AUDIO_DIR,
    TMP_DIR,
    BASE_DIR,
)
from utils import now_iso, ensure_ascii


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


def build_audio_paths(session_id: str, request_id: str, message_id: str) -> dict:
    date_path = datetime.now().strftime("%Y/%m/%d")
    audio_session_dir = AUDIO_DIR / date_path / session_id
    audio_session_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{message_id}.webm"
    stored_path = audio_session_dir / stored_filename
    webm_path = TMP_DIR / f"{request_id}.webm"
    wav_path = TMP_DIR / f"{request_id}.wav"
    return {
        "date_path": date_path,
        "audio_session_dir": audio_session_dir,
        "stored_filename": stored_filename,
        "stored_path": stored_path,
        "webm_path": webm_path,
        "wav_path": wav_path,
    }


def persist_uploaded_audio(data: bytes, stored_path: Path, webm_path: Path):
    stored_path.write_bytes(data)
    webm_path.write_bytes(data)


def build_public_audio_urls(wav_path: Path, stored_path: Path) -> tuple[str, str]:
    public_wav_url = f"{NGROK_PUBLIC_URL}/download/{wav_path.name}"
    public_audio_url = f"/audio/{stored_path.relative_to(AUDIO_DIR).as_posix()}"
    return public_wav_url, public_audio_url


def build_audio_registry_item(
    *,
    audio_id: str,
    session_id: str,
    message_id: str,
    session_title: str,
    input_type: str,
    original_filename: str,
    stored_filename: str,
    stored_path: Path,
    public_url: str,
    content_type: str,
    transcript: str,
    assistant_reply: str,
) -> dict:
    return {
        "audioId": audio_id,
        "sessionId": session_id,
        "messageId": message_id,
        "sessionTitle": session_title,
        "inputType": input_type,
        "originalFilename": original_filename,
        "storedFilename": stored_filename,
        "storedPath": stored_path.relative_to(BASE_DIR).as_posix(),
        "publicUrl": public_url,
        "contentType": content_type,
        "sizeBytes": stored_path.stat().st_size if stored_path.exists() else 0,
        "transcript": transcript,
        "assistantReply": assistant_reply,
        "createdAt": now_iso(),
        "isOrphaned": False,
    }


def cleanup_temp_audio_files(webm_path: Path, wav_path: Path):
    if webm_path.exists():
        webm_path.unlink(missing_ok=True)
    if wav_path.exists():
        wav_path.unlink(missing_ok=True)


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
