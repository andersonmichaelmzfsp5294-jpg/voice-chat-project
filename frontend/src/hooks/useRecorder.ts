import { useRef, useState } from "react";

export type RecorderStatus =
  | "idle"
  | "requesting_permission"
  | "recording"
  | "stopped"
  | "error";

export function useRecorder() {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [inputLevel, setInputLevel] = useState(0); // 0~1

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  // 电平监测：AudioContext + RAF
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafIdRef = useRef<number | null>(null);

  const cleanupAudioMeter = () => {
    if (rafIdRef.current != null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setInputLevel(0);
  };

  const startAudioMeter = async (stream: MediaStream) => {
    cleanupAudioMeter();

    const AudioCtxCtor = (window.AudioContext ||
      (window as any).webkitAudioContext) as typeof AudioContext;

    const ctx = new AudioCtxCtor();
    audioCtxRef.current = ctx;

    // 关键：有些浏览器会让 AudioContext 初始是 suspended，需要 resume
    if (ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch {
        // ignore
      }
    }

    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;

    source.connect(analyser);

    // 关键：用 0 音量的 Gain 接到 destination，保证音频图在跑，但不外放（避免啸叫）
    const silentGain = ctx.createGain();
    silentGain.gain.value = 0;
    analyser.connect(silentGain);
    silentGain.connect(ctx.destination);

    const dataArray = new Uint8Array(analyser.fftSize);

    const tick = () => {
      analyser.getByteTimeDomainData(dataArray);

      // RMS（声音越大 rms 越大）
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        const v = (dataArray[i] - 128) / 128; // -1~1
        sum += v * v;
      }
      const rms = Math.sqrt(sum / dataArray.length);

      // 放大一点方便观察（你可以改成 *6 更敏感）
      const level = Math.min(1, rms * 5);
      setInputLevel(level);

      rafIdRef.current = requestAnimationFrame(tick);
    };

    rafIdRef.current = requestAnimationFrame(tick);
  };

  const start = async (deviceId?: string) => {
    try {
      setErrorMessage("");
      setAudioBlob(null);
      setStatus("requesting_permission");

      const audioConstraints: MediaTrackConstraints = {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      };

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: audioConstraints,
      });

      streamRef.current = stream;

      // 开始电平监测（await 让它更稳）
      await startAudioMeter(stream);

      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "";

      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined
      );

      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: mimeType || "audio/webm",
        });

        cleanupAudioMeter();

        if (blob.size === 0) {
          setStatus("error");
          setErrorMessage("录音为空：请至少说 2-3 秒后再停止。");
          streamRef.current?.getTracks().forEach((t) => t.stop());
          streamRef.current = null;
          return;
        }

        setAudioBlob(blob);
        setStatus("stopped");

        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setStatus("recording");
    } catch (err) {
      console.error(err);
      cleanupAudioMeter();
      setStatus("error");
      setErrorMessage("无法访问麦克风：请检查权限/是否被其他软件占用。");
    }
  };

  const stop = () => {
    if (mediaRecorderRef.current && status === "recording") {
      mediaRecorderRef.current.stop();
    }
  };

  const reset = () => {
    cleanupAudioMeter();
    setAudioBlob(null);
    setErrorMessage("");
    setStatus("idle");
  };

  return {
    status,
    audioBlob,
    errorMessage,
    inputLevel,
    start,
    stop,
    reset,
  };
}