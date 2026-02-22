"use client";

import * as React from "react";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";
import type { ProviderId, UploadedFile } from "@/lib/types";
import { uploadFiles } from "@/lib/api";
import { AttachmentChips } from "./AttachmentChips";
import { createSttController, stopSpeaking, speakText, type SpeechState } from "@/lib/speech";

type Props = {
  provider: ProviderId;
  model: string;
  sending: boolean;
  onSend: (text: string, attachments: UploadedFile[]) => void;
};

export function Composer({ provider, model, sending, onSend }: Props) {
  const [text, setText] = React.useState("");
  const [pendingFiles, setPendingFiles] = React.useState<UploadedFile[]>([]);
  const [uploading, setUploading] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  // STT
  const [speech, setSpeech] = React.useState<SpeechState>({ status: "idle" });
  const sttRef = React.useRef<ReturnType<typeof createSttController> | null>(null);

  React.useEffect(() => {
    sttRef.current = createSttController({
      onInterim: () => {},
      onFinal: (t) => {
        if (!t) return;
        setText((prev) => (prev ? (prev.endsWith(" ") ? prev + t : prev + " " + t) : t));
      },
      onState: (s) => setSpeech(s),
    });
  }, []);

  const listening = speech.status === "listening";
  const canSend = (text.trim().length > 0 || pendingFiles.length > 0) && !sending && !uploading;

  function toggleMic() {
    if (listening) {
      sttRef.current?.stop();
    } else {
      sttRef.current?.start();
    }
  }

  function doSend() {
    if (!canSend) return;
    onSend(text.trim(), pendingFiles);
    setText("");
    setPendingFiles([]);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  }

  async function handlePickFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      const uploaded = await uploadFiles(Array.from(files));
      setPendingFiles((prev) => [...prev, ...uploaded]);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    await handlePickFiles(e.dataTransfer.files);
  }

  return (
    <div
      className="border-t border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950"
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
    >
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        onChange={(e) => handlePickFiles(e.target.files)}
      />

      {/* Attachment chips + status above input */}
      {(pendingFiles.length > 0 || speech.status === "denied" || speech.status === "unsupported" || speech.status === "error") && (
        <div className="px-3 pt-2">
          <AttachmentChips
            files={pendingFiles}
            onRemove={(id) => setPendingFiles((prev) => prev.filter((f) => f.file_id !== id))}
          />
          {speech.status === "denied" && <div className="text-xs text-red-500">Mic denied — enable microphone permission.</div>}
          {speech.status === "unsupported" && <div className="text-xs text-amber-600 dark:text-amber-400">STT not supported in this browser.</div>}
          {speech.status === "error" && <div className="text-xs text-red-500">STT error: {(speech as any).message}</div>}
        </div>
      )}

      {/* Main row: textarea + controls side by side */}
      <div className="flex items-start gap-2 px-3 py-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            uploading ? "Uploading…" :
            sending ? "Sending…" :
            listening ? "Listening… speak now" :
            "Message…"
          }
          rows={2}
          className="flex-1 resize-none bg-transparent text-sm outline-none"
        />

        {/* Controls: Send on top, three icons below */}
        <div className="flex flex-col items-center gap-1">
          <button
            type="button"
            onClick={doSend}
            disabled={!canSend}
            title="Send message"
            className="flex h-9 items-center gap-1.5 rounded-xl bg-zinc-900 px-3 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
              <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
            </svg>
            Send
          </button>

          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={sending || uploading}
              title="Attach"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 disabled:opacity-40 dark:hover:bg-zinc-800"
            >
              📎
            </button>

            <button
              type="button"
              onClick={toggleMic}
              title={listening ? "Stop" : "Dictate"}
              className={`flex h-7 w-7 items-center justify-center rounded-lg text-sm transition-colors ${
                listening ? "bg-red-50 text-red-500 dark:bg-red-950" : "text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800"
              }`}
            >
              {listening ? "⏹" : "🎙️"}
            </button>

            <button
              type="button"
              onClick={() => stopSpeaking()}
              title="Stop TTS"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800"
            >
              🔇
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
