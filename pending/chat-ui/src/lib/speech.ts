"use client";

export type SpeechState =
  | { status: "idle" }
  | { status: "listening"; interim: string }
  | { status: "denied" }
  | { status: "unsupported" }
  | { status: "error"; message: string };

type WebSpeechRecognition = any;

function getRecognitionCtor(): any | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function createSttController(opts: {
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
  onState: (s: SpeechState) => void;
}) {
  const Ctor = getRecognitionCtor();
  if (!Ctor) {
    opts.onState({ status: "unsupported" });
    return {
      supported: false,
      start: () => {},
      stop: () => {}
    };
  }

  let recog: WebSpeechRecognition | null = null;

  const start = () => {
    try {
      if (!recog) {
        recog = new Ctor();
        recog.continuous = true;
        recog.interimResults = true;
        recog.lang = "en-US";

        recog.onresult = (evt: any) => {
          let interim = "";
          let finalText = "";
          for (let i = evt.resultIndex; i < evt.results.length; i++) {
            const res = evt.results[i];
            const txt = res[0]?.transcript ?? "";
            if (res.isFinal) finalText += txt;
            else interim += txt;
          }
          if (interim) opts.onInterim(interim);
          if (finalText) opts.onFinal(finalText.trim());
          opts.onState({ status: "listening", interim });
        };

        recog.onerror = (e: any) => {
          if (e?.error === "not-allowed" || e?.error === "service-not-allowed") {
            opts.onState({ status: "denied" });
            return;
          }
          opts.onState({ status: "error", message: String(e?.error || "stt error") });
        };

        recog.onend = () => {
          opts.onState({ status: "idle" });
        };
      }

      opts.onState({ status: "listening", interim: "" });
      recog.start();
    } catch (err: any) {
      opts.onState({ status: "error", message: err?.message ?? String(err) });
    }
  };

  const stop = () => {
    try {
      recog?.stop?.();
      opts.onState({ status: "idle" });
    } catch {
      opts.onState({ status: "idle" });
    }
  };

  return { supported: true, start, stop };
}

export function speakText(text: string, opts?: { rate?: number; pitch?: number }) {
  if (typeof window === "undefined") return;
  const synth = window.speechSynthesis;
  if (!synth) return;

  // Cancel any ongoing speech (supports barge-in)
  synth.cancel();

  const u = new SpeechSynthesisUtterance(text);
  u.rate = opts?.rate ?? 1;
  u.pitch = opts?.pitch ?? 1;

  synth.speak(u);
}

export function stopSpeaking() {
  if (typeof window === "undefined") return;
  window.speechSynthesis?.cancel?.();
}
