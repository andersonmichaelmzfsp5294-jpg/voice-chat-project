import type { RefObject } from "react";

type TtsPlayerCardProps = {
  visible: boolean;
  ttsCurrentSegmentIndex: number | null;
  ttsCurrentSrc: string;
  ttsIsPlaying: boolean;
  ttsPlayerRef: RefObject<HTMLAudioElement>;
};

export default function TtsPlayerCard({
  visible,
  ttsCurrentSegmentIndex,
  ttsCurrentSrc,
  ttsIsPlaying,
  ttsPlayerRef,
}: TtsPlayerCardProps) {
  if (!visible) return null;

  return (
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
  );
}
