import os
from pathlib import Path

# =========================
# 环境变量
# =========================
VOLC_APP_ID = os.getenv("VOLC_APP_ID", "").strip()
VOLC_ACCESS_TOKEN = os.getenv("VOLC_ACCESS_TOKEN", "").strip()
NGROK_PUBLIC_URL = os.getenv("NGROK_PUBLIC_URL", "").strip().rstrip("/")
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "").strip()
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")

ARK_API_KEY = os.getenv("ARK_API_KEY", "").strip()
ARK_MODEL = os.getenv("ARK_MODEL", "").strip()
ARK_BASE_URL = os.getenv(
    "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
).strip().rstrip("/")
ARK_TIMEOUT_SEC = float(os.getenv("ARK_TIMEOUT_SEC", "45"))
ARK_MAX_TOKENS = int(os.getenv("ARK_MAX_TOKENS", "512"))

TTS_APP_ID = os.getenv("TTS_APP_ID", "").strip()
TTS_ACCESS_TOKEN = os.getenv("TTS_ACCESS_TOKEN", "").strip()
TTS_RESOURCE_ID = os.getenv("TTS_RESOURCE_ID", "volc.service_type.10029").strip()
TTS_VOICE_TYPE = os.getenv(
    "TTS_VOICE_TYPE", "zh_female_daimengchuanmei_moon_bigtts"
).strip()
TTS_UNI_URL = os.getenv(
    "TTS_UNI_URL", "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
).strip()
TTS_WS_RESOURCE_ID = os.getenv(
    "TTS_WS_RESOURCE_ID", "volc.service_type.10029"
).strip()
TTS_WS_URL = os.getenv(
    "TTS_WS_URL", "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
).strip()
TTS_ENCODING = os.getenv("TTS_ENCODING", "mp3").strip()
TTS_UID = os.getenv("TTS_UID", "wayfarer").strip()

TTS_SEGMENT_HARD_LEN = int(os.getenv("TTS_SEGMENT_HARD_LEN", "18"))
TTS_SEGMENT_SOFT_MIN_LEN = int(os.getenv("TTS_SEGMENT_SOFT_MIN_LEN", "6"))
TTS_SEGMENT_SOFT_WAIT_SEC = float(os.getenv("TTS_SEGMENT_SOFT_WAIT_SEC", "0.4"))

MAX_HISTORY_ROUNDS = int(os.getenv("MAX_HISTORY_ROUNDS", "8"))

ARK_SYSTEM_PROMPT = (
    "你是一个猫娘（猫耳、尾巴的可爱女孩），请用轻松可爱、亲切、口语化的中文回答。"
    "请遵守以下规则："
    "1）回答自然、简洁、口语化；"
    "2）优先短答，适合聊天界面阅读；"
    "3）不做医学诊断，不替代医生；"
    "4）当信息不足时，优先追问一个最关键的问题；"
    "5）不要编造用户没有说过的事实。"
).strip()

# =========================
# 豆包 AUC 录音文件识别
# =========================
AUC_SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
AUC_QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
AUC_RESOURCE_ID = "volc.seedasr.auc"

# =========================
# 临时目录 / 数据目录
# =========================
BASE_DIR = Path(__file__).parent
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

STORE_FILE = DATA_DIR / "chat_store.json"
AUDIO_DIR = DATA_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_REGISTRY_FILE = DATA_DIR / "audio_registry.json"
TTS_SEGMENTS_DIR = DATA_DIR / "tts_segments"
TTS_SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
