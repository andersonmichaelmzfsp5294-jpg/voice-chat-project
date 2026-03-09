import { useState } from "react";
import type { Dispatch, KeyboardEvent, MutableRefObject, SetStateAction } from "react";
import { API_BASE } from "../config";
import { requestFullTts, streamSSE } from "../api/chatApi";
import { resolveAudioUrl, uid } from "../utils/chatUtils";
import type { ChatMsg } from "../types/chat";

type UseTextChatParams = {
  currentSessionId: string;
  setCurrentSessionId: (id: string) => void;
  setCurrentSessionTitle: (title: string) => void;
  setMessages: Dispatch<SetStateAction<ChatMsg[]>>;
  refreshSessions: () => Promise<void>;
  resetTtsPlayback: () => void;
  enqueueTtsSegment: (event: any) => void;
  playNextTtsSegment: () => void;
  ttsAudioDoneRef: MutableRefObject<boolean>;
  setAutoPlayAudioUrl: (value: string) => void;
  setBackendStatus: (value: string) => void;
  setIsUploading: (value: boolean) => void;
  setPendingSince: (value: number | null) => void;
  setThinkingSeconds: (value: number) => void;
  setLastLatencySeconds: (value: number | null) => void;
  isUploading: boolean;
  isHydratingSession: boolean;
};

export function useTextChat({
  currentSessionId,
  setCurrentSessionId,
  setCurrentSessionTitle,
  setMessages,
  refreshSessions,
  resetTtsPlayback,
  enqueueTtsSegment,
  playNextTtsSegment,
  ttsAudioDoneRef,
  setAutoPlayAudioUrl,
  setBackendStatus,
  setIsUploading,
  setPendingSince,
  setThinkingSeconds,
  setLastLatencySeconds,
  isUploading,
  isHydratingSession,
}: UseTextChatParams) {
  const [textInput, setTextInput] = useState("");

  async function handleSendText() {
    if (isUploading || isHydratingSession) return;

    const trimmed = textInput.trim();
    if (!trimmed) return;

    resetTtsPlayback();

    const assistantMsgId = uid();
    const startedAt = performance.now();
    const placeholder = "正在思考…";
    let streamSucceeded = false;
    let assistantText = "";

    setMessages((prev) => [
      ...prev,
      {
        id: uid(),
        role: "user",
        text: trimmed,
        createdAt: new Date().toISOString(),
      },
      {
        id: assistantMsgId,
        role: "assistant",
        text: placeholder,
        localOnly: true,
      },
    ]);

    setTextInput("");

    try {
      setIsUploading(true);
      setPendingSince(startedAt);
      setLastLatencySeconds(null);
      setBackendStatus("后端：发送中…");

      await streamSSE(
        `${API_BASE}/chat/text/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: trimmed,
            sessionId: currentSessionId || null,
          }),
        },
        (event) => {
          if (event.type === "start") {
            if (event.sessionId) setCurrentSessionId(event.sessionId);
            if (event.sessionTitle) setCurrentSessionTitle(event.sessionTitle);
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
                      text: m.text === placeholder ? assistantText : assistantText,
                    }
                  : m
              )
            );
            return;
          }

          if (event.type === "audio_segment") {
            enqueueTtsSegment(event);
            return;
          }

          if (event.type === "audio_done") {
            ttsAudioDoneRef.current = true;
            playNextTtsSegment();
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
      setIsUploading(false);
      setPendingSince(null);
      setThinkingSeconds(0);
      setLastLatencySeconds((performance.now() - startedAt) / 1000);
    }
  }

  function handleTextKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSendText();
    }
  }

  return {
    textInput,
    setTextInput,
    handleSendText,
    handleTextKeyDown,
  };
}
