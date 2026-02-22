"use client";

import type { ProviderId, UploadedFile, ModelInfo } from "./types";

export async function fetchModels(provider: ProviderId): Promise<ModelInfo[]> {
  const res = await fetch(`/api/models?provider=${provider}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load models");
  const data = await res.json();
  return data.models as ModelInfo[];
}

export async function uploadFiles(files: File[]): Promise<UploadedFile[]> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const res = await fetch("/api/files", { method: "POST", body: fd });
  if (!res.ok) throw new Error("Upload failed");
  const data = await res.json();
  return data.files as UploadedFile[];
}

export type ChatStreamEvent =
  | { type: "delta"; text: string }
  | { type: "done" }
  | { type: "error"; message: string };

export async function streamChat(req: {
  provider: ProviderId;
  model: string;
  messages: { role: "system" | "user" | "assistant"; content: string }[];
  file_ids: string[];
}): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req)
  });
  if (!res.ok || !res.body) throw new Error("Chat request failed");
  return res.body.getReader();
}

export function parseSseLines(buffer: string): { events: ChatStreamEvent[]; rest: string } {
  const events: ChatStreamEvent[] = [];
  const parts = buffer.split("\n\n");
  const complete = parts.slice(0, -1);
  const rest = parts[parts.length - 1] ?? "";

  for (const block of complete) {
    const line = block.split("\n").find((l) => l.startsWith("data: "));
    if (!line) continue;
    const payload = line.replace(/^data:\s*/, "").trim();
    if (payload === "[DONE]") {
      events.push({ type: "done" });
      continue;
    }
    try {
      const obj = JSON.parse(payload);
      if (obj.type === "delta") events.push({ type: "delta", text: String(obj.text ?? "") });
      else if (obj.type === "error") events.push({ type: "error", message: String(obj.message ?? "error") });
    } catch {
      // ignore malformed
    }
  }
  return { events, rest };
}
