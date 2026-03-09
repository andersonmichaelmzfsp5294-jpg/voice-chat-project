import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import TTS_SEGMENTS_DIR
from models import TtsFullRequest
from tts_service import synthesize_tts_v1_full_text


def get_router():
    router = APIRouter()

    @router.get("/tts/{filename}")
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

    @router.post("/tts/full")
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

    return router
