from fastapi import APIRouter, HTTPException

from config import (
    TMP_DIR,
    STORE_FILE,
    VOLC_APP_ID,
    VOLC_ACCESS_TOKEN,
    NGROK_PUBLIC_URL,
    ARK_API_KEY,
    ARK_MODEL,
    ARK_BASE_URL,
)
from storage_utils import load_store
from session_service import (
    list_sessions_meta as list_sessions_meta_service,
    get_session_detail as get_session_detail_service,
    delete_session_data as delete_session_data_service,
)


def get_router(store_lock):
    router = APIRouter()

    @router.get("/health")
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

    @router.get("/sessions")
    async def get_sessions():
        async with store_lock:
            return {"items": list_sessions_meta_service()}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        async with store_lock:
            session = get_session_detail_service(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        async with store_lock:
            ok = delete_session_data_service(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True}

    return router
