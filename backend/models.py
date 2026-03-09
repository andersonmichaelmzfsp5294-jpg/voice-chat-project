from pydantic import BaseModel


class TextChatRequest(BaseModel):
    text: str
    sessionId: str | None = None


class TtsFullRequest(BaseModel):
    text: str
