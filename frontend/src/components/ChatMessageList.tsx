import type { RefObject } from "react";
import type { ChatMsg } from "../types/chat";
import { resolveAudioUrl } from "../utils/chatUtils";

type ChatMessageListProps = {
  messages: ChatMsg[];
  autoPlayAudioUrl: string;
  onAutoPlayHandled: () => void;
  endRef: RefObject<HTMLDivElement>;
};

export default function ChatMessageList({
  messages,
  autoPlayAudioUrl,
  onAutoPlayHandled,
  endRef,
}: ChatMessageListProps) {
  return (
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
                          onAutoPlayHandled();
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
  );
}
