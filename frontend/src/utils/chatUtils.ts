import { API_BASE } from "../config";
import type { ChatMsg } from "../types/chat";

export function uid() {
  return Math.random().toString(36).slice(2);
}

export function formatTimeLabel(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  const sameDay =
    now.getFullYear() === date.getFullYear() &&
    now.getMonth() === date.getMonth() &&
    now.getDate() === date.getDate();

  if (sameDay) {
    return date.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  return date.toLocaleDateString("zh-CN", {
    month: "numeric",
    day: "numeric",
  });
}

export function cleanupAudioUrls(messages: ChatMsg[]) {
  messages.forEach((m) => {
    if (m.audioUrl?.startsWith("blob:")) {
      URL.revokeObjectURL(m.audioUrl);
    }
  });
}

export function resolveAudioUrl(url?: string) {
  if (!url) return "";
  if (url.startsWith("blob:")) return url;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  if (url.startsWith("/")) return `${API_BASE}${url}`;
  return `${API_BASE}/${url.replace(/^\/+/, "")}`;
}
