"use client";

import * as React from "react";
import { Button } from "@/components/ui/Button";
import { createSttController, speakText, stopSpeaking, type SpeechState } from "@/lib/speech";

export default function VoicePage() {
  const [speech, setSpeech] = React.useState<SpeechState>({ status: "idle" });
  const [transcript, setTranscript] = React.useState("");
  const sttRef = React.useRef<ReturnType<typeof createSttController> | null>(null);

  React.useEffect(() => {
    sttRef.current = createSttController({
      onInterim: (t) => setSpeech({ status: "listening", interim: t }),
      onFinal: (t) => setTranscript((prev) => (prev ? prev + " " + t : t)),
      onState: (s) => setSpeech(s)
    });
  }, []);

  return (
    <div className="space-y-3">
      <div>
        <div className="text-lg font-semibold">Voice</div>
        <div className="text-sm text-zinc-500 dark:text-zinc-400">
          Starter voice workspace: browser STT + browser TTS. Full duplex voice chat is a next step (WebRTC/AudioWorklet + server TTS/STT).
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex flex-wrap gap-2">
          {speech.status === "listening" ? (
            <Button variant="danger" onClick={() => sttRef.current?.stop()}>
              Stop Listening
            </Button>
          ) : (
            <Button onClick={() => sttRef.current?.start()}>Start Listening</Button>
          )}
          <Button variant="ghost" onClick={() => speakText(transcript || "Hello from the voice page.")}>
            Speak (TTS)
          </Button>
          <Button variant="ghost" onClick={() => stopSpeaking()}>
            Stop TTS
          </Button>
          <Button variant="ghost" onClick={() => setTranscript("")}>
            Clear
          </Button>
        </div>

        <div className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
          STT Status:{" "}
          {speech.status === "listening"
            ? "Listening…"
            : speech.status === "denied"
            ? "Mic denied"
            : speech.status === "unsupported"
            ? "Unsupported"
            : speech.status === "error"
            ? "Error"
            : "Idle"}
          {speech.status === "listening" && speech.interim ? <span className="ml-2 italic opacity-70">({speech.interim})</span> : null}
        </div>

        <div className="mt-3 whitespace-pre-wrap rounded-xl border border-zinc-200 bg-zinc-50 p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
          {transcript || "Transcript will appear here."}
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="font-semibold">Next step for “full voice chat mode”</div>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-600 dark:text-zinc-300">
          <li>Use AudioWorklet/WebRTC to capture mic continuously and detect end-of-utterance reliably.</li>
          <li>Stream audio to /api/stt (server) for accurate cross-browser STT.</li>
          <li>Stream assistant audio from /api/tts (server) and support barge-in by pausing playback instantly.</li>
          <li>Keep UI states: Listening → Thinking → Speaking, with interrupt/stop controls.</li>
        </ul>
      </div>
    </div>
  );
}
