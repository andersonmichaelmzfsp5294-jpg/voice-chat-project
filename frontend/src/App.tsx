import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import { useRecorder } from "./hooks/useRecorder";
import { API_BASE } from "./config";
import {
  deleteSessionOnBackend,
  fetchSessionDetail,
  fetchSessions,
  requestFullTts,
  streamSSE,
} from "./api/chatApi";
import type { ChatMsg, SessionMeta } from "./types/chat";
import {
  cleanupAudioUrls,
  formatTimeLabel,
  resolveAudioUrl,
  uid,
} from "./utils/chatUtils";

export default function App() {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);

  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [currentSessionTitle, setCurrentSessionTitle] = useState<string>("新对话");
  const [messages, setMessages] = useState<ChatMsg[]>([]);

  const [backendStatus, setBackendStatus] = useState<string>("后端：未请求");
  const [isUploading, setIsUploading] = useState(false);
  const [isHydratingSession, setIsHydratingSession] = useState(false);
  const [textInput, setTextInput] = useState("");
  const [pendingSince, setPendingSince] = useState<number | null>(null);
  const [thinkingSeconds, setThinkingSeconds] = useState(0);
  const [lastLatencySeconds, setLastLatencySeconds] = useState<number | null>(null);
  const [ttsPlayerVisible, setTtsPlayerVisible] = useState(false);
  const [ttsCurrentSegmentIndex, setTtsCurrentSegmentIndex] = useState<number | null>(
    null
  );
  const [ttsIsPlaying, setTtsIsPlaying] = useState(false);
  const [ttsCurrentSrc, setTtsCurrentSrc] = useState("");
  const [autoPlayAudioUrl, setAutoPlayAudioUrl] = useState("");

  const endRef = useRef<HTMLDivElement | null>(null);
  const ttsPlayerRef = useRef<HTMLAudioElement | null>(null);
  const ttsQueueRef = useRef<
    { segmentId?: string; audioUrl: string; index: number }[]
  >([]);
  const ttsPlayingRef = useRef(false);
  const ttsExpectedIndexRef = useRef(1);
  const ttsAudioDoneRef = useRef(false);

  const { status, audioBlob, errorMessage, inputLevel, start, stop, reset } =
    useRecorder();

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
  }, []);

  function resetTtsPlayback() {
    ttsQueueRef.current = [];
    ttsExpectedIndexRef.current = 1;
    ttsAudioDoneRef.current = false;
    ttsPlayingRef.current = false;
    const audio = ttsPlayerRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    setTtsPlayerVisible(false);
    setTtsCurrentSegmentIndex(null);
    setTtsCurrentSrc("");
    setTtsIsPlaying(false);
  }

  function playNextTtsSegment() {
    if (ttsPlayingRef.current) return;
    const queue = ttsQueueRef.current;
    if (queue.length === 0) return;

    queue.sort((a, b) => a.index - b.index);
    let next = queue[0];
    if (next.index !== ttsExpectedIndexRef.current) {
      if (!ttsAudioDoneRef.current) return;
      ttsExpectedIndexRef.current = next.index;
      next = queue[0];
    }

    queue.shift();
    ttsPlayingRef.current = true;

    const audio = ttsPlayerRef.current;
    if (!audio) {
      window.setTimeout(() => playNextTtsSegment(), 0);
      return;
    }

    const src = resolveAudioUrl(next.audioUrl);
    setTtsCurrentSegmentIndex(next.index);
    setTtsCurrentSrc(src);

    const finish = () => {
      ttsPlayingRef.current = false;
      setTtsIsPlaying(false);
      ttsExpectedIndexRef.current = next.index + 1;
      playNextTtsSegment();
    };

    audio.onplay = () => setTtsIsPlaying(true);
    audio.onpause = () => setTtsIsPlaying(false);
    audio.onended = finish;
    audio.onerror = () => {
      console.warn("TTS 音频播放失败");
      finish();
    };

    audio.src = src;
    audio.load();
    audio.play().catch((err) => {
      console.warn("TTS 音频播放被阻止", err);
      finish();
    });
  }

  function enqueueTtsSegment(segment: {
    segmentId?: string;
    audioUrl?: string;
    index?: number;
  }) {
    if (!segment.audioUrl || segment.index == null) return;
    setTtsPlayerVisible(true);
    ttsQueueRef.current.push({
      segmentId: segment.segmentId,
      audioUrl: segment.audioUrl,
      index: segment.index,
    });
    playNextTtsSegment();
  }

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

  useEffect(() => {
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  function handleTextKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSendText();
    }
  }

  async function handleRecordClick() {
    if (isUploading || isHydratingSession) return;

    if (status === "recording") {
      stop();
      return;
    }

    if (status === "stopped") reset();
    await start();
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
    reset();
  }

  async function handleDeleteSession(
    e: React.MouseEvent<HTMLButtonElement>,
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

  const levelPct = Math.round(inputLevel * 100);
  const canSendText =
    !isUploading && !isHydratingSession && textInput.trim().length > 0;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-top">
          <div className="brand-row">
            <div className="brand-mark">A</div>
            <div className="brand-text">
              <div className="brand-title">认知筛查助手</div>
              <div className="brand-subtitle">Voice Chat Prototype</div>
            </div>
          </div>

          <button className="new-chat-btn" onClick={handleNewChat} disabled={isUploading}>
            ＋ 新对话
          </button>
        </div>

        <div className="sidebar-section-title">历史会话</div>

        <div className="session-list">
          {sessionsLoading ? (
            <div className="sidebar-empty">正在加载历史记录…</div>
          ) : sessions.length === 0 ? (
            <div className="sidebar-empty">还没有历史会话</div>
          ) : (
            sessions.map((item) => {
              const active = item.id === currentSessionId;
              return (
                <div
                  key={item.id}
                  className={`session-item ${active ? "active" : ""}`}
                  onClick={() => openSession(item.id)}
                >
                  <div className="session-item-main">
                    <div className="session-title">{item.title || "新对话"}</div>
                    <div className="session-preview">
                      {item.lastPreview || "暂无内容"}
                    </div>
                  </div>

                  <div className="session-actions">
                    <span className="session-time">{formatTimeLabel(item.updatedAt)}</span>
                    <button
                      className="delete-btn"
                      onClick={(e) => handleDeleteSession(e, item.id)}
                      title="删除会话"
                    >
                      ×
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="sidebar-footer">
          <div className="footer-chip">AUC</div>
          <div className="footer-chip">Ark</div>
          <div className="footer-chip">History</div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <div className="topbar-title">{currentSessionTitle || "新对话"}</div>
            <div className="topbar-subtitle">
              Session：{currentSessionId || "草稿会话"}
            </div>
          </div>
          <div className="topbar-badge">语音 + 文字</div>
        </header>

        <section className="chat-scroll">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-title">开始一段新的对话</div>
              <div className="empty-desc">
                文字 + 语音都可用：输入文本或点击录音发送，系统会自动生成回复。
              </div>
              <div className="empty-hints">
                <div className="hint-card">“你好，我们先测试一下。”</div>
                <div className="hint-card">“我叫张三，你记住了吗？”</div>
                <div className="hint-card">“请用一句话介绍你自己。”</div>
              </div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map((m) => {
                const audioSrc = resolveAudioUrl(m.audioUrl);
                return (
                  <div
                    key={m.id}
                    className={`message-row ${m.role === "user" ? "user" : "assistant"}`}
                  >
                    <div className={`message-bubble ${m.role}`}>
                      {m.text && <div className="message-text">{m.text}</div>}
                      {audioSrc && (
                        <audio
                          controls
                          preload="metadata"
                          src={audioSrc}
                          className="audio-player"
                          autoPlay={audioSrc === autoPlayAudioUrl}
                          onPlay={() => {
                            if (audioSrc === autoPlayAudioUrl) {
                              setAutoPlayAudioUrl("");
                            }
                          }}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
              <div ref={endRef} />
            </div>
          )}
        </section>

        <footer className="composer-wrap">
          <div className="status-bar">
            <span>前端：{statusText}</span>
            <span>｜{backendStatus}</span>
            <span>｜电平：{levelPct}%</span>
            {pendingSince != null ? (
              <span>｜思考时间：{thinkingSeconds.toFixed(1)}s</span>
            ) : lastLatencySeconds != null ? (
              <span>｜上次耗时：{lastLatencySeconds.toFixed(1)}s</span>
            ) : null}
            {errorMessage && <span className="status-error">｜{errorMessage}</span>}
          </div>

          {ttsPlayerVisible && (
            <div className="tts-player-card">
              <div className="tts-player-title">??????</div>
              <div className="tts-player-meta">
                {ttsCurrentSegmentIndex != null
                  ? `???? #${ttsCurrentSegmentIndex}`
                  : "????"}
                {ttsCurrentSrc ? " ? ???" : ""}
                {ttsIsPlaying ? " ? ???" : " ? ??"}
              </div>
              <audio
                ref={ttsPlayerRef}
                controls
                preload="metadata"
                className="tts-control-player"
              />
            </div>
          )}

          <div className="composer">
            <button
              className={`record-btn ${status === "recording" ? "recording" : ""}`}
              onClick={handleRecordClick}
              disabled={isUploading || isHydratingSession}
            >
              {isUploading
                ? "处理中…"
                : status === "recording"
                ? "停止录音"
                : "开始录音"}
            </button>

            <div className="composer-center">
              <div className="composer-title">
                {status === "recording"
                  ? "正在录音，点击停止后自动发送"
                  : "当前为语音聊天模式"}
              </div>
              <div className="level-track">
                <div className="level-fill" style={{ width: `${levelPct}%` }} />
              </div>

              <div className="text-input-row">
                <textarea
                  className="text-input"
                  placeholder="输入文字，Enter 发送，Shift+Enter 换行"
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  onKeyDown={handleTextKeyDown}
                  rows={3}
                  disabled={isUploading || isHydratingSession}
                />
                <button
                  className="send-btn"
                  onClick={handleSendText}
                  disabled={!canSendText}
                >
                  发送
                </button>
              </div>
            </div>

            <button
              className="secondary-btn"
              onClick={handleNewChat}
              disabled={isUploading}
            >
              新会话
            </button>
          </div>
        </footer>
      </main>
    </div>
  );
}
