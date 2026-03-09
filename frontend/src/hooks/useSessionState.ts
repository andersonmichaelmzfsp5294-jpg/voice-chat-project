import { useState } from "react";
import type { MouseEvent } from "react";
import type { ChatMsg, SessionMeta } from "../types/chat";
import {
  deleteSessionOnBackend,
  fetchSessionDetail,
  fetchSessions,
} from "../api/chatApi";

type UseSessionStateParams = {
  isUploading: boolean;
  resetTtsPlayback: () => void;
  cleanupAudioUrls: (messages: ChatMsg[]) => void;
  setBackendStatus: (value: string) => void;
  setTextInput: (value: string) => void;
  setPendingSince: (value: number | null) => void;
  setThinkingSeconds: (value: number) => void;
  setLastLatencySeconds: (value: number | null) => void;
  resetRecorder: () => void;
  setIsHydratingSession: (value: boolean) => void;
};

export function useSessionState({
  isUploading,
  resetTtsPlayback,
  cleanupAudioUrls,
  setBackendStatus,
  setTextInput,
  setPendingSince,
  setThinkingSeconds,
  setLastLatencySeconds,
  resetRecorder,
  setIsHydratingSession,
}: UseSessionStateParams) {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [currentSessionTitle, setCurrentSessionTitle] = useState<string>("新对话");
  const [messages, setMessages] = useState<ChatMsg[]>([]);

  async function refreshSessions() {
    const data = await fetchSessions();
    setSessions(data.items);

    if (!currentSessionId && data.items.length === 0) {
      setCurrentSessionTitle("新对话");
      setMessages([]);
    }
  }

  async function openSession(sessionId: string) {
    if (isUploading) return;
    if (!sessionId) return;

    resetTtsPlayback();
    setIsHydratingSession(true);
    try {
      const detail = await fetchSessionDetail(sessionId);
      cleanupAudioUrls(messages);
      setCurrentSessionId(detail.id);
      setCurrentSessionTitle(detail.title || "新对话");
      setMessages(detail.messages || []);
      setBackendStatus("后端：已加载历史会话");
      setTextInput("");
      setPendingSince(null);
      setThinkingSeconds(0);
      setLastLatencySeconds(null);
    } catch (e: any) {
      setBackendStatus(`后端：加载会话失败 ❌ ${e?.message ?? String(e)}`);
    } finally {
      setIsHydratingSession(false);
    }
  }

  async function bootstrap() {
    setSessionsLoading(true);
    try {
      const data = await fetchSessions();
      setSessions(data.items);

      if (data.items.length > 0) {
        const firstId = data.items[0].id;
        const detail = await fetchSessionDetail(firstId);
        setCurrentSessionId(detail.id);
        setCurrentSessionTitle(detail.title || "新对话");
        setMessages(detail.messages || []);
        setBackendStatus("后端：历史会话已加载");
      } else {
        setCurrentSessionId("");
        setCurrentSessionTitle("新对话");
        setMessages([]);
        setBackendStatus("后端：未请求");
      }
    } catch (e: any) {
      setBackendStatus(`后端：初始化失败 ❌ ${e?.message ?? String(e)}`);
    } finally {
      setSessionsLoading(false);
    }
  }

  function handleNewChat() {
    if (isUploading) return;

    resetTtsPlayback();
    cleanupAudioUrls(messages);
    setCurrentSessionId("");
    setCurrentSessionTitle("新对话");
    setMessages([]);
    setBackendStatus("后端：未请求");
    setTextInput("");
    setPendingSince(null);
    setThinkingSeconds(0);
    setLastLatencySeconds(null);
    resetRecorder();
  }

  async function handleDeleteSession(
    e: MouseEvent<HTMLButtonElement>,
    sessionId: string
  ) {
    e.stopPropagation();
    if (isUploading) return;

    const ok = window.confirm("确定删除这个会话吗？");
    if (!ok) return;

    try {
      await deleteSessionOnBackend(sessionId);
      const updated = await fetchSessions();
      setSessions(updated.items);

      if (currentSessionId === sessionId) {
        cleanupAudioUrls(messages);
        resetTtsPlayback();

        if (updated.items.length > 0) {
          const nextId = updated.items[0].id;
          const detail = await fetchSessionDetail(nextId);
          setCurrentSessionId(detail.id);
          setCurrentSessionTitle(detail.title || "新对话");
          setMessages(detail.messages || []);
        } else {
          setCurrentSessionId("");
          setCurrentSessionTitle("新对话");
          setMessages([]);
        }

        setTextInput("");
        setPendingSince(null);
        setThinkingSeconds(0);
        setLastLatencySeconds(null);
      }
    } catch (e: any) {
      setBackendStatus(`后端：删除会话失败 ❌ ${e?.message ?? String(e)}`);
    }
  }

  return {
    sessions,
    sessionsLoading,
    currentSessionId,
    currentSessionTitle,
    messages,
    setCurrentSessionId,
    setCurrentSessionTitle,
    setMessages,
    refreshSessions,
    openSession,
    bootstrap,
    handleNewChat,
    handleDeleteSession,
  };
}
