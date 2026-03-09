type TopbarProps = {
  currentSessionTitle: string;
  currentSessionId: string;
};

export default function Topbar({
  currentSessionTitle,
  currentSessionId,
}: TopbarProps) {
  return (
    <header className="topbar">
      <div>
        <div className="topbar-title">{currentSessionTitle || "新对话"}</div>
        <div className="topbar-subtitle">
          Session：{currentSessionId || "草稿会话"}
        </div>
      </div>
      <div className="topbar-badge">语音 + 文字</div>
    </header>
  );
}
