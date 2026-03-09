import { useEffect } from "react";
import { API_BASE } from "../config";
import { requestFullTts, streamSSE } from "../api/chatApi";
import { resolveAudioUrl, uid } from "../utils/chatUtils";
import type { ChatMsg } from "../types/chat";
import type { Dispatch, SetStateAction } from "react";

type UseAudioChatParams = {
  audioBlob: Blob | null;
  currentSessionId: string;
  setCurrentSessionId: (id: string) => void;
  setCurrentSessionTitle: (title: string) => void;
  setMessages: Dispatch<SetStateAction<ChatMsg[]>>;
  refreshSessions: () => Promise<void>;
  resetTtsPlayback: () => void;
  setBackendStatus: (value: string) => void;
  setIsUploading: (value: boolean) => void;
  setPendingSince: (value: number | null) => void;
  setThinkingSeconds: (value: number) => void;
  setLastLatencySeconds: (value: number | null) => void;
  setAutoPlayAudioUrl: (value: string) => void;
};

export function useAudioChat({
  audioBlob,
  currentSessionId,
  setCurrentSessionId,
  setCurrentSessionTitle,
  setMessages,
  refreshSessions,
  resetTtsPlayback,
  setBackendStatus,
  setIsUploading,
  setPendingSince,
  setThinkingSeconds,
  setLastLatencySeconds,
  setAutoPlayAudioUrl,
}: UseAudioChatParams) {
  useEffect(() => {
    if (!audioBlob) return;

    resetTtsPlayback();
    const audioUrl = URL.createObjectURL(audioBlob);
    const audioMsgId = uid();
    const assistantMsgId = uid();
    const startedAt = performance.now();
    const placeholder = "正在思考…";
    let cancelled = false;
    let streamSucceeded = false;
    let assistantText = "";

    setMessages((prev) => [
      ...prev,
      {
        id: audioMsgId,
        role: "user",
        text: "语音消息（转写中…）",
        audioUrl,
        localOnly: true,
      },
      {
        id: assistantMsgId,
        role: "assistant",
        text: placeholder,
        localOnly: true,
      },
    ]);

    (async () => {
      try {
        setIsUploading(true);
        setPendingSince(startedAt);
        setLastLatencySeconds(null);
        setBackendStatus("后端：上传中…");

        const form = new FormData();
        form.append("audio", audioBlob, "recording.webm");
        if (currentSessionId) form.append("sessionId", currentSessionId);
        form.append("deviceLabel", "browser");

        await streamSSE(
          `${API_BASE}/chat/audio/stream`,
          {
            method: "POST",
            body: form,
          },
          (event) => {
            if (cancelled) return;

            if (event.type === "start") {
              if (event.sessionId) setCurrentSessionId(event.sessionId);
              if (event.sessionTitle) setCurrentSessionTitle(event.sessionTitle);
              if (event.transcript) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === audioMsgId
                      ? {
                          ...m,
                          text: event.transcript,
                          createdAt: new Date().toISOString(),
                        }
                      : m
                  )
                );
              }
              return;
            }

            if (event.type === "delta") {
              const delta = event.content || "";
              if (!delta) return;
              assistantText += delta;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? {
                        ...m,
                        text: assistantText,
                      }
                    : m
                )
              );
              return;
            }

            if (event.type === "done") {
              streamSucceeded = true;
              if (!assistantText.trim()) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, text: "（模型未返回内容）", localOnly: true }
                      : m
                  )
                );
              }
              setBackendStatus("后端：已返回结果 ✅");
              return;
            }

            if (event.type === "error") {
              setBackendStatus("后端：请求失败 ❌");
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? {
                        ...m,
                        text: `调用失败：${event.message ?? "未知错误"}`,
                        localOnly: true,
                      }
                    : m
                )
              );
            }
          }
        );

        if (streamSucceeded) {
          if (assistantText.trim()) {
            void (async () => {
              const audioUrl = await requestFullTts(assistantText);
              if (audioUrl) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, text: assistantText, audioUrl }
                      : m
                  )
                );
                setAutoPlayAudioUrl(resolveAudioUrl(audioUrl));
              }
            })();
          }
          await refreshSessions();
        }
      } catch (e: any) {
        if (cancelled) return;

        setBackendStatus("后端：请求失败 ❌");
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? {
                  ...m,
                  text: `调用失败：${e?.message ?? String(e)}`,
                  localOnly: true,
                }
              : m
          )
        );
      } finally {
        if (!cancelled) {
          setIsUploading(false);
          setPendingSince(null);
          setThinkingSeconds(0);
          setLastLatencySeconds((performance.now() - startedAt) / 1000);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioBlob]);
}
