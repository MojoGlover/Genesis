"use client";

import * as React from "react";
import { v4 as uuidv4 } from "uuid";
import type { ChatMessage, ProviderId, UploadedFile } from "@/lib/types";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { Composer } from "@/components/chat/Composer";
import { fetchModels, parseSseLines, streamChat } from "@/lib/api";
import { loadSettings, saveSettings, type UiSettings } from "@/lib/storage";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { speakText, stopSpeaking } from "@/lib/speech";

export default function ChatPage() {
  const [settings, setSettings] = React.useState<UiSettings>(() => ({
    ...loadSettings()
  }));

  const [models, setModels] = React.useState<{ id: string; label: string }[]>([]);
  const [status, setStatus] = React.useState<"idle" | "streaming" | "error">("idle");
  const [error, setError] = React.useState<string | null>(null);

  const [messages, setMessages] = React.useState<ChatMessage[]>([
    {
      id: uuidv4(),
      role: "assistant",
      content:
        "This is the PlugOps Chat UI Starter.\n\n✅ File uploads\n✅ Speech-to-text\n✅ Voice chat mode button\n✅ Desktop/tablet/phone responsive shell\n\nWire /api/chat to your gateway when ready.",
      createdAt: Date.now()
    }
  ]);

  const listRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  React.useEffect(() => {
    (async () => {
      try {
        const m = await fetchModels(settings.provider);
        setModels(m);
        if (!settings.model && m[0]?.id) setSettings((s) => ({ ...s, model: m[0].id }));
      } catch (e: any) {
        setModels([]);
      }
    })();
  }, [settings.provider]);

  React.useEffect(() => {
    // auto-scroll on new messages
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  async function send(text: string, attachments: UploadedFile[]) {
    setError(null);
    setStatus("streaming");

    const userMsg: ChatMessage = {
      id: uuidv4(),
      role: "user",
      content: text || (attachments.length ? "Sent attachments." : ""),
      createdAt: Date.now(),
      attachments
    };

    const assistantId = uuidv4();
    const assistantMsg: ChatMessage = { id: assistantId, role: "assistant", content: "", createdAt: Date.now() };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    try {
      const reader = await streamChat({
        provider: settings.provider as ProviderId,
        model: settings.model,
        messages: [
          ...messages
            .filter((m) => m.role !== "system")
            .map((m) => ({ role: m.role, content: m.content })),
          { role: "user", content: userMsg.content }
        ],
        file_ids: attachments.map((a) => a.file_id)
      });

      const dec = new TextDecoder();
      let buf = "";
      let fullText = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parsed = parseSseLines(buf);
        buf = parsed.rest;

        for (const ev of parsed.events) {
          if (ev.type === "delta") {
            fullText += ev.text;
            setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: fullText } : m)));
          } else if (ev.type === "error") {
            throw new Error(ev.message);
          } else if (ev.type === "done") {
            // complete
          }
        }
      }

      setStatus("idle");

      if (settings.ttsEnabled && fullText.trim()) {
        // speak in chunks to avoid long utterance issues
        stopSpeaking();
        const chunk = fullText.slice(0, 800);
        speakText(chunk);
      }
    } catch (e: any) {
      setStatus("error");
      setError(e?.message ?? "Chat failed");
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, content: "⚠️ Error: " + (e?.message ?? "chat failed") } : m))
      );
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      {/* Left panel (desktop). On mobile, use the top nav drawer in shell. */}
      <aside className="hidden lg:block">
        <div className="rounded-2xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950">
          <div className="mb-2 text-sm font-semibold">Session</div>
          <div className="space-y-2 text-sm">
            <div className="rounded-xl border border-zinc-200 p-2 dark:border-zinc-800">
              <div className="text-xs text-zinc-500">Provider</div>
              <div className="mt-1 flex gap-2">
                <Button
                  size="sm"
                  variant={settings.provider === "local" ? "default" : "ghost"}
                  onClick={() => setSettings((s) => ({ ...s, provider: "local", model: "" }))}
                >
                  Local
                </Button>
                <Button
                  size="sm"
                  variant={settings.provider === "hosted" ? "default" : "ghost"}
                  onClick={() => setSettings((s) => ({ ...s, provider: "hosted", model: "" }))}
                >
                  Hosted
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-zinc-200 p-2 dark:border-zinc-800">
              <div className="text-xs text-zinc-500">Model</div>
              <select
                className="mt-1 h-10 w-full rounded-xl border border-zinc-200 bg-white px-3 text-sm dark:border-zinc-800 dark:bg-zinc-950"
                value={settings.model}
                onChange={(e) => setSettings((s) => ({ ...s, model: e.target.value }))}
              >
                {models.length ? (
                  models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))
                ) : (
                  <option value="">(no models)</option>
                )}
              </select>
            </div>

            <div className="rounded-xl border border-zinc-200 p-2 dark:border-zinc-800">
              <label className="flex items-center justify-between gap-2 text-sm">
                <span>TTS replies</span>
                <input
                  type="checkbox"
                  checked={settings.ttsEnabled}
                  onChange={(e) => setSettings((s) => ({ ...s, ttsEnabled: e.target.checked }))}
                />
              </label>
            </div>

            <div className="rounded-xl border border-zinc-200 p-2 text-xs text-zinc-500 dark:border-zinc-800">
              Status:{" "}
              <span className={status === "error" ? "text-red-500" : status === "streaming" ? "text-amber-600 dark:text-amber-400" : ""}>
                {status}
              </span>
              {error ? <div className="mt-1 text-red-500">{error}</div> : null}
            </div>
          </div>
        </div>
      </aside>

      <section className="min-h-[70dvh]">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div>
            <div className="text-lg font-semibold">Chat</div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              Drag files into the composer. Use Mic for dictation. Voice button is wired for UI state (full duplex is next step).
            </div>
          </div>
          <Button
            variant="ghost"
            onClick={() =>
              setMessages([
                {
                  id: uuidv4(),
                  role: "assistant",
                  content: "Fresh chat. Upload files, dictate, or start voice mode.",
                  createdAt: Date.now()
                }
              ])
            }
          >
            New
          </Button>
        </div>

        <div
          ref={listRef}
          className="scrollbar-thin h-[52dvh] overflow-y-auto rounded-2xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950"
        >
          <div className="flex flex-col gap-3">
            {messages.map((m) => (
              <MessageBubble key={m.id} msg={m} />
            ))}
          </div>
        </div>

        <div className="safe-bottom mt-3 -mx-3">
          <Composer provider={settings.provider as ProviderId} model={settings.model} sending={status === "streaming"} onSend={send} />
        </div>
      </section>
    </div>
  );
}
