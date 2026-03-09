import { API_BASE } from "../config";
import type { SessionDetail, SessionMeta, StreamEvent } from "../types/chat";

export async function fetchSessions() {
  const res = await fetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error("获取会话列表失败");
  return (await res.json()) as { items: SessionMeta[] };
}

export async function fetchSessionDetail(sessionId: string) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`);
  if (!res.ok) throw new Error("获取会话详情失败");
  return (await res.json()) as SessionDetail;
}

export async function deleteSessionOnBackend(sessionId: string) {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("删除会话失败");
}

export async function streamSSE(
  url: string,
  options: RequestInit,
  onEvent: (event: StreamEvent) => void
) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`后端错误：${res.status} ${txt}`);
  }
  if (!res.body) {
    throw new Error("后端未返回可读流");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finished = false;

  while (!finished) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");

    let idx = buffer.indexOf("\n\n");
    while (idx !== -1) {
      const raw = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 2);

      if (raw) {
        const dataLines = raw
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.replace(/^data:\s?/, "").trim());

        if (dataLines.length > 0) {
          const dataStr = dataLines.join("\n");
          try {
            const payload = JSON.parse(dataStr) as StreamEvent;
            onEvent(payload);
            if (payload.type === "done" || payload.type === "error") {
              finished = true;
              try {
                await reader.cancel();
              } catch {
                // ignore
              }
              break;
            }
          } catch {
            // ignore parse errors
          }
        }
      }

      idx = buffer.indexOf("\n\n");
    }
  }
}

export async function requestFullTts(text: string) {
  const trimmed = text.trim();
  if (!trimmed) return null;

  try {
    const res = await fetch(`${API_BASE}/tts/full`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: trimmed }),
    });

    if (!res.ok) {
      const txt = await res.text();
      console.error(`TTS full request failed: ${res.status} ${txt}`);
      return null;
    }

    const data = (await res.json()) as { audioUrl?: string };
    return data.audioUrl ?? null;
  } catch (e: any) {
    console.error(`TTS full request failed: ${e?.message ?? String(e)}`);
    return null;
  }
}
