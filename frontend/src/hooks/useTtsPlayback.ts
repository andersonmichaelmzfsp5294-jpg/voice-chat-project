import { useRef, useState } from "react";
import { resolveAudioUrl } from "../utils/chatUtils";

type TtsQueueItem = { segmentId?: string; audioUrl: string; index: number };

type TtsSegment = {
  segmentId?: string;
  audioUrl?: string;
  index?: number;
};

export function useTtsPlayback() {
  const [ttsPlayerVisible, setTtsPlayerVisible] = useState(false);
  const [ttsCurrentSegmentIndex, setTtsCurrentSegmentIndex] = useState<number | null>(
    null
  );
  const [ttsIsPlaying, setTtsIsPlaying] = useState(false);
  const [ttsCurrentSrc, setTtsCurrentSrc] = useState("");
  const [autoPlayAudioUrl, setAutoPlayAudioUrl] = useState("");

  const ttsPlayerRef = useRef<HTMLAudioElement | null>(null);
  const ttsQueueRef = useRef<TtsQueueItem[]>([]);
  const ttsPlayingRef = useRef(false);
  const ttsExpectedIndexRef = useRef(1);
  const ttsAudioDoneRef = useRef(false);

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

  function enqueueTtsSegment(segment: TtsSegment) {
    if (!segment.audioUrl || segment.index == null) return;
    setTtsPlayerVisible(true);
    ttsQueueRef.current.push({
      segmentId: segment.segmentId,
      audioUrl: segment.audioUrl,
      index: segment.index,
    });
    playNextTtsSegment();
  }

  return {
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
  };
}
