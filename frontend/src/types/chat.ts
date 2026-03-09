export type Role = "user" | "assistant";

export type ChatMsg = {
  id: string;
  role: Role;
  text?: string;
  audioId?: string;
  audioUrl?: string;
  inputType?: "text" | "audio";
  createdAt?: string;
  localOnly?: boolean;
};

export type SessionMeta = {
  id: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  lastPreview?: string;
};

export type SessionDetail = {
  id: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  messages: ChatMsg[];
};

export type StreamEvent =
  | {
      type: "start";
      sessionId?: string;
      sessionTitle?: string;
      transcript?: string;
    }
  | { type: "delta"; content?: string }
  | { type: "audio_segment"; segmentId?: string; audioUrl?: string; index?: number }
  | { type: "audio_done" }
  | { type: "done" }
  | { type: "error"; message?: string };
