import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import { useRecorder } from "./hooks/useRecorder";
import { useTtsPlayback } from "./hooks/useTtsPlayback";
import { useSessionState } from "./hooks/useSessionState";
import { useTextChat } from "./hooks/useTextChat";
import { useAudioChat } from "./hooks/useAudioChat";
import {
  cleanupAudioUrls,
  formatTimeLabel,
} from "./utils/chatUtils";
import Sidebar from "./components/Sidebar";
import Topbar from "./components/Topbar";
import ChatMessageList from "./components/ChatMessageList";
import StatusBar from "./components/StatusBar";
import TtsPlayerCard from "./components/TtsPlayerCard";
import Composer from "./components/Composer";

export default function App() {
  const [backendStatus, setBackendStatus] = useState<string>("后端：未请求");
  const [isUploading, setIsUploading] = useState(false);
  const [isHydratingSession, setIsHydratingSession] = useState(false);
  const [pendingSince, setPendingSince] = useState<number | null>(null);
  const [thinkingSeconds, setThinkingSeconds] = useState(0);
  const [lastLatencySeconds, setLastLatencySeconds] = useState<number | null>(null);

  const {
    ttsPlayerVisible,
    ttsCurrentSegmentIndex,
    ttsIsPlaying,
    ttsCurrentSrc,
    autoPlayAudioUrl,
    setAutoPlayAudioUrl,
    ttsPlayerRef,
    ttsAudioDoneRef,
    resetTtsPlayback,
    playNextTtsSegment,
    enqueueTtsSegment,
  } = useTtsPlayback();

  const endRef = useRef<HTMLDivElement | null>(null);
  const textInputSetterRef = useRef<(value: string) => void>(() => {});

  const { status, audioBlob, errorMessage, inputLevel, start, stop, reset } =
    useRecorder();

  const {
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
  } = useSessionState({
    isUploading,
    resetTtsPlayback,
    cleanupAudioUrls,
    setBackendStatus,
    setTextInput: (value) => textInputSetterRef.current(value),
    setPendingSince,
    setThinkingSeconds,
    setLastLatencySeconds,
    resetRecorder: reset,
    setIsHydratingSession,
  });

  const {
    textInput,
    setTextInput,
    handleSendText,
    handleTextKeyDown,
  } = useTextChat({
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
  });

  textInputSetterRef.current = setTextInput;

  useAudioChat({
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
  });

  const isPending = isUploading || pendingSince != null;

  const statusText = useMemo(() => {
    if (isPending) return "等待后端返回中…";
    if (isHydratingSession) return "加载历史会话中…";

    switch (status) {
      case "idle":
        return "空闲";
      case "requesting_permission":
        return "请求麦克风权限中…";
      case "recording":
        return "录音中…";
      case "stopped":
        return "录音完成";
      case "error":
        return "录音错误";
      default:
        return status;
    }
  }, [status, isPending, isHydratingSession]);

  useEffect(() => {
    if (pendingSince == null) {
      setThinkingSeconds(0);
      return;
    }

    const tick = () => {
      setThinkingSeconds((performance.now() - pendingSince) / 1000);
    };

    tick();
    const id = window.setInterval(tick, 100);
    return () => window.clearInterval(id);
  }, [pendingSince]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isUploading]);

  useEffect(() => {
    return () => {
      resetTtsPlayback();
    };
  }, [resetTtsPlayback]);

  useEffect(() => {
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleRecordClick() {
    if (isUploading || isHydratingSession) return;

    if (status === "recording") {
      stop();
      return;
    }

    if (status === "stopped") reset();
    await start();
  }

  const levelPct = Math.round(inputLevel * 100);
  const canSendText =
    !isUploading && !isHydratingSession && textInput.trim().length > 0;

  return (
    <div className="app-shell">
      <Sidebar
        sessions={sessions}
        sessionsLoading={sessionsLoading}
        currentSessionId={currentSessionId}
        isUploading={isUploading}
        onNewChat={handleNewChat}
        onOpenSession={openSession}
        onDeleteSession={handleDeleteSession}
        formatTimeLabel={formatTimeLabel}
      />

      <main className="main-panel">
        <Topbar
          currentSessionTitle={currentSessionTitle}
          currentSessionId={currentSessionId}
        />

        <ChatMessageList
          messages={messages}
          autoPlayAudioUrl={autoPlayAudioUrl}
          onAutoPlayHandled={() => setAutoPlayAudioUrl("")}
          endRef={endRef}
        />

        <footer className="composer-wrap">
          <StatusBar
            statusText={statusText}
            backendStatus={backendStatus}
            levelPct={levelPct}
            pendingSince={pendingSince}
            thinkingSeconds={thinkingSeconds}
            lastLatencySeconds={lastLatencySeconds}
            errorMessage={errorMessage}
          />

          <TtsPlayerCard
            visible={ttsPlayerVisible}
            ttsCurrentSegmentIndex={ttsCurrentSegmentIndex}
            ttsCurrentSrc={ttsCurrentSrc}
            ttsIsPlaying={ttsIsPlaying}
            ttsPlayerRef={ttsPlayerRef}
          />

          <Composer
            status={status}
            isUploading={isUploading}
            isHydratingSession={isHydratingSession}
            levelPct={levelPct}
            textInput={textInput}
            onTextChange={setTextInput}
            onTextKeyDown={handleTextKeyDown}
            onSendText={handleSendText}
            canSendText={canSendText}
            onRecordClick={handleRecordClick}
            onNewChat={handleNewChat}
          />
        </footer>
      </main>
    </div>
  );
}
