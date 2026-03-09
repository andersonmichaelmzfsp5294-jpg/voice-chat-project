import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from chat_service import (
    build_chat_messages as build_chat_messages_service,
    iter_ark_stream as iter_ark_stream_service,
    generate_reply_with_memory as generate_reply_with_memory_service,
)
from config import (
    ARK_MODEL,
    MAX_HISTORY_ROUNDS,
    TTS_ENCODING,
    TTS_SEGMENT_SOFT_WAIT_SEC,
    TTS_SEGMENTS_DIR,
)
from models import TextChatRequest
from session_service import (
    append_chat_turn as append_chat_turn_service,
    get_session_detail as get_session_detail_service,
)
from tts_service import (
    has_tts_env,
    pop_tts_segment,
    synthesize_tts_segment,
)
from utils import (
    sse_event,
    make_session_id,
    make_user_message,
    shorten_title,
)


def get_router(store_lock):
    router = APIRouter()

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

    @router.post("/chat/text")
    async def chat_text(payload: TextChatRequest):
        user_text = (payload.text or "").strip()
        if not user_text:
            raise HTTPException(status_code=400, detail="text is required")

        sid = payload.sessionId or make_session_id()
        rid = str(uuid.uuid4())

        try:
            assistant_text, session = await generate_reply_with_memory_service(
                session_id=sid,
                user_text=user_text,
                history_provider=get_model_history,
                append_chat_turn_func=append_chat_turn,
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

    @router.post("/chat/text/stream")
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

                messages = await build_chat_messages_service(
                    session_id=sid,
                    user_text=user_text,
                    history_provider=get_model_history,
                )
                async for delta in iter_ark_stream_service(messages):
                    assistant_parts.append(delta)
                    yield sse_event({"type": "delta", "content": delta})

                assistant_text = "".join(assistant_parts).strip()
                await append_chat_turn(sid, user_message, assistant_text)

                yield sse_event({"type": "done"})
            except Exception as e:
                yield sse_event({"type": "error", "message": str(e)})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/chat/text/stream-tts")
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

                    messages = await build_chat_messages_service(
                        session_id=sid,
                        user_text=user_text,
                        history_provider=get_model_history,
                    )
                    async for delta in iter_ark_stream_service(messages):
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

    return router
