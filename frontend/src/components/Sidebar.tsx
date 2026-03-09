import type { MouseEvent } from "react";
import type { SessionMeta } from "../types/chat";

type SidebarProps = {
  sessions: SessionMeta[];
  sessionsLoading: boolean;
  currentSessionId: string;
  isUploading: boolean;
  onNewChat: () => void;
  onOpenSession: (id: string) => void;
  onDeleteSession: (e: MouseEvent<HTMLButtonElement>, id: string) => void;
  formatTimeLabel: (value?: string) => string;
};

export default function Sidebar({
  sessions,
  sessionsLoading,
  currentSessionId,
  isUploading,
  onNewChat,
  onOpenSession,
  onDeleteSession,
  formatTimeLabel,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <div className="brand-row">
          <div className="brand-mark">A</div>
          <div className="brand-text">
            <div className="brand-title">认知筛查助手</div>
            <div className="brand-subtitle">Voice Chat Prototype</div>
          </div>
        </div>

        <button className="new-chat-btn" onClick={onNewChat} disabled={isUploading}>
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
                onClick={() => onOpenSession(item.id)}
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
                    onClick={(e) => onDeleteSession(e, item.id)}
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
  );
}
