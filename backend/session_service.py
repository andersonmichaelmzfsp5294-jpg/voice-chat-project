from storage_utils import (
    load_store,
    save_store,
    load_audio_registry,
    save_audio_registry,
)
from utils import make_session, shorten_title, now_iso, make_message


def list_sessions_meta() -> list[dict]:
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


def get_session_detail(session_id: str) -> dict | None:
    data = load_store()
    return data.get("sessions", {}).get(session_id)


def append_chat_turn(session_id: str, user_message: dict, assistant_text: str) -> dict:
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


def delete_session_data(session_id: str) -> bool:
    data = load_store()
    sessions = data.get("sessions", {})
    existed = session_id in sessions
    if existed:
        sessions.pop(session_id, None)
        save_store(data)
        registry = load_audio_registry()
        changed = False
        for item in registry.get("items", []):
            if item.get("sessionId") == session_id and not item.get(
                "isOrphaned", False
            ):
                item["isOrphaned"] = True
                changed = True
        if changed:
            save_audio_registry(registry)
    return existed
