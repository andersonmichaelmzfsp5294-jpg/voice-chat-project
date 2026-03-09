import json

from config import AUDIO_REGISTRY_FILE, STORE_FILE


def ensure_store_file():
    if not STORE_FILE.exists():
        STORE_FILE.write_text(
            json.dumps({"sessions": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def ensure_audio_registry_file():
    if not AUDIO_REGISTRY_FILE.exists():
        AUDIO_REGISTRY_FILE.write_text(
            json.dumps({"items": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_store() -> dict:
    ensure_store_file()
    try:
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {"sessions": {}}
        STORE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data


def save_store(data: dict):
    tmp_path = STORE_FILE.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp_path.replace(STORE_FILE)


def load_audio_registry() -> dict:
    ensure_audio_registry_file()
    try:
        return json.loads(AUDIO_REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {"items": []}
        AUDIO_REGISTRY_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data


def save_audio_registry(data: dict):
    tmp_path = AUDIO_REGISTRY_FILE.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp_path.replace(AUDIO_REGISTRY_FILE)
