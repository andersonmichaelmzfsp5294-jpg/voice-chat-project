import re
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from audio_service import (
    require_auc_env,
    ensure_ffmpeg,
    convert_webm_to_wav,
    auc_submit_and_query,
    build_audio_paths,
    persist_uploaded_audio,
    build_public_audio_urls,
    build_audio_registry_item,
    cleanup_temp_audio_files,
)
from chat_service import (
    build_chat_messages as build_chat_messages_service,
    iter_ark_stream as iter_ark_stream_service,
    generate_reply_with_memory as generate_reply_with_memory_service,
    require_ark_env,
)
from config import (
    ARK_MODEL,
    AUDIO_DIR,
    TMP_DIR,
    MAX_HISTORY_ROUNDS,
)
from session_service import (
    append_chat_turn as append_chat_turn_service,
    get_session_detail as get_session_detail_service,
)
from storage_utils import load_audio_registry, save_audio_registry
from utils import (
    sse_event,
    make_session_id,
    make_message_id,
    make_audio_id,
    make_user_message,
    shorten_title,
)


def get_router(store_lock):
    router = APIRouter()

    async def append_audio_registry_item(item: dict):
        async with store_lock:
            data = load_audio_registry()
            items = data.setdefault("items", [])
            items.append(item)
            save_audio_registry(data)

    async def get_session_detail(session_id: str) -> dict | None:
        async with store_lock:
            return get_session_detail_service(session_id)

    async def append_chat_turn(session_id: str, user_message: dict, assistant_text: str) -> dict:
        async with store_lock:
            return append_chat_turn_service(session_id, user_message, assistant_text)

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

    async def resolve_session_title(session_id: str, fallback_text: str) -> str:
        session = await get_session_detail(session_id)
        title = (session or {}).get("title") if session else None
        if title:
            return title
        return shorten_title(fallback_text) if fallback_text else "新对话"

    @router.get("/download/{filename}")
    def download_file(filename: str):
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

    @router.get("/audio/{subpath:path}")
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

    @router.get("/audio-registry")
    def get_audio_registry():
        return load_audio_registry()

    @router.post("/chat/audio")
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

        audio_paths = build_audio_paths(sid, rid, message_id)
        stored_filename = audio_paths["stored_filename"]
        stored_path = audio_paths["stored_path"]
        webm_path = audio_paths["webm_path"]
        wav_path = audio_paths["wav_path"]

        try:
            data = await audio.read()
            persist_uploaded_audio(data, stored_path, webm_path)

            convert_webm_to_wav(webm_path, wav_path)

            public_wav_url, public_audio_url = build_public_audio_urls(
                wav_path, stored_path
            )

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

            assistant_text, session = await generate_reply_with_memory_service(
                session_id=sid,
                user_text=final_text,
                history_provider=get_model_history,
                append_chat_turn_func=append_chat_turn,
                user_message=user_message,
            )

            await append_audio_registry_item(
                build_audio_registry_item(
                    audio_id=audio_id,
                    session_id=sid,
                    message_id=message_id,
                    session_title=session.get("title", "新对话"),
                    input_type="audio",
                    original_filename=audio.filename or "recording.webm",
                    stored_filename=stored_filename,
                    stored_path=stored_path,
                    public_url=public_audio_url,
                    content_type=audio.content_type or "audio/webm",
                    transcript=final_text,
                    assistant_reply=assistant_text,
                )
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
            cleanup_temp_audio_files(webm_path, wav_path)

    @router.post("/chat/audio/stream")
    async def chat_audio_stream(
        audio: UploadFile = File(...),
        sessionId: str | None = Form(default=None),
        deviceLabel: str | None = Form(default=None),
    ):
        sid = sessionId or make_session_id()
        rid = str(uuid.uuid4())
        message_id = make_message_id()
        audio_id = make_audio_id()

        audio_paths = build_audio_paths(sid, rid, message_id)
        stored_filename = audio_paths["stored_filename"]
        stored_path = audio_paths["stored_path"]
        webm_path = audio_paths["webm_path"]
        wav_path = audio_paths["wav_path"]

        async def event_stream():
            assistant_parts: list[str] = []
            try:
                require_auc_env()
                require_ark_env()
                ensure_ffmpeg()

                data = await audio.read()
                persist_uploaded_audio(data, stored_path, webm_path)

                convert_webm_to_wav(webm_path, wav_path)

                public_wav_url, public_audio_url = build_public_audio_urls(
                    wav_path, stored_path
                )

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

                messages = await build_chat_messages_service(
                    session_id=sid,
                    user_text=final_text,
                    history_provider=get_model_history,
                )
                async for delta in iter_ark_stream_service(messages):
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
                    build_audio_registry_item(
                        audio_id=audio_id,
                        session_id=sid,
                        message_id=message_id,
                        session_title=session.get("title", "新对话"),
                        input_type="audio",
                        original_filename=audio.filename or "recording.webm",
                        stored_filename=stored_filename,
                        stored_path=stored_path,
                        public_url=public_audio_url,
                        content_type=audio.content_type or "audio/webm",
                        transcript=final_text,
                        assistant_reply=assistant_text,
                    )
                )

                yield sse_event({"type": "done"})
            except Exception as e:
                yield sse_event({"type": "error", "message": str(e)})
            finally:
                cleanup_temp_audio_files(webm_path, wav_path)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
