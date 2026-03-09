type StatusBarProps = {
  statusText: string;
  backendStatus: string;
  levelPct: number;
  pendingSince: number | null;
  thinkingSeconds: number;
  lastLatencySeconds: number | null;
  errorMessage?: string;
};

export default function StatusBar({
  statusText,
  backendStatus,
  levelPct,
  pendingSince,
  thinkingSeconds,
  lastLatencySeconds,
  errorMessage,
}: StatusBarProps) {
  return (
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
  );
}
