import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOW_ORIGINS
from routes_audio import get_router as get_audio_router
from routes_chat import get_router as get_chat_router
from routes_session import get_router as get_session_router
from routes_tts import get_router as get_tts_router

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

app.include_router(get_session_router(STORE_LOCK))
app.include_router(get_tts_router())
app.include_router(get_chat_router(STORE_LOCK))
app.include_router(get_audio_router(STORE_LOCK))
