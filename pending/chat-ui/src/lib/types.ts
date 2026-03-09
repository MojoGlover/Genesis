export type ProviderId = "local" | "hosted";

export type ChatRole = "system" | "user" | "assistant";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: number;
  attachments?: UploadedFile[];
};

export type UploadedFile = {
  file_id: string;
  name: string;
  mime: string;
  size: number;
  url?: string; // optional if you later add downloads
};

export type ModelInfo = { id: string; label: string };
