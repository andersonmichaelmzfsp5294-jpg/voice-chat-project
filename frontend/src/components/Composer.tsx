import type { KeyboardEvent } from "react";

type ComposerProps = {
  status: string;
  isUploading: boolean;
  isHydratingSession: boolean;
  levelPct: number;
  textInput: string;
  onTextChange: (value: string) => void;
  onTextKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSendText: () => void;
  canSendText: boolean;
  onRecordClick: () => void;
  onNewChat: () => void;
};

export default function Composer({
  status,
  isUploading,
  isHydratingSession,
  levelPct,
  textInput,
  onTextChange,
  onTextKeyDown,
  onSendText,
  canSendText,
  onRecordClick,
  onNewChat,
}: ComposerProps) {
  return (
    <div className="composer">
      <button
        className={`record-btn ${status === "recording" ? "recording" : ""}`}
        onClick={onRecordClick}
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
            onChange={(e) => onTextChange(e.target.value)}
            onKeyDown={onTextKeyDown}
            rows={3}
            disabled={isUploading || isHydratingSession}
          />
          <button className="send-btn" onClick={onSendText} disabled={!canSendText}>
            发送
          </button>
        </div>
      </div>

      <button className="secondary-btn" onClick={onNewChat} disabled={isUploading}>
        新会话
      </button>
    </div>
  );
}
