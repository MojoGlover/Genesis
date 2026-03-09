import { NextRequest } from "next/server";

export const runtime = "nodejs";

const OLLAMA_BASE = "http://localhost:11434";
const ENGINEER0_BASE = "http://localhost:5001"; // Engineer0 HTTP API
const DEFAULT_LOCAL_MODEL = "blackzero:latest";

type ReqBody = {
  provider: "local" | "hosted";
  model: string;
  messages: { role: "system" | "user" | "assistant"; content: string }[];
  file_ids: string[];
};

function sse(data: unknown) {
  return `data: ${JSON.stringify(data)}\n\n`;
}

function errStream(message: string) {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      c.enqueue(enc.encode(sse({ type: "error", message })));
      c.enqueue(enc.encode("data: [DONE]\n\n"));
      c.close();
    },
  });
}

// ── Engineer0 via HTTP API ────────────────────────────────────────────────────
async function streamEngineer0(body: ReqBody): Promise<ReadableStream> {
  const userMsg = [...body.messages].reverse().find((m) => m.role === "user")?.content ?? "";

  let res: Response;
  try {
    res = await fetch(`${ENGINEER0_BASE}/api/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer rf187WXceunnHSc7T_G6GBPH73ib2lQJMYlfSeya7fY",
      },
      body: JSON.stringify({ message: userMsg }),
    });
  } catch {
    return errStream("Engineer0 unreachable — is it running on port 5001?");
  }

  if (!res.ok) return errStream(`Engineer0 error: ${res.status}`);

  const data = await res.json();
  const text: string = data.response ?? data.message ?? JSON.stringify(data);

  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      // Simulate streaming by chunking the response
      let i = 0;
      const interval = setInterval(() => {
        if (i >= text.length) {
          c.enqueue(enc.encode("data: [DONE]\n\n"));
          clearInterval(interval);
          c.close();
          return;
        }
        const chunk = text.slice(i, i + 12);
        i += 12;
        c.enqueue(enc.encode(sse({ type: "delta", text: chunk })));
      }, 20);
    },
  });
}

// ── Ollama streaming ──────────────────────────────────────────────────────────
async function streamOllama(body: ReqBody): Promise<ReadableStream> {
  const model = body.model || DEFAULT_LOCAL_MODEL;

  let ollamaRes: Response;
  try {
    ollamaRes = await fetch(`${OLLAMA_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages: body.messages, stream: true }),
    });
  } catch {
    return errStream("Ollama unreachable — is it running?");
  }

  const reader = ollamaRes.body!.getReader();
  const enc = new TextEncoder();
  const dec = new TextDecoder();

  return new ReadableStream({
    async start(controller) {
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const obj = JSON.parse(line);
            const text = obj?.message?.content ?? "";
            if (text) controller.enqueue(enc.encode(sse({ type: "delta", text })));
            if (obj?.done) {
              controller.enqueue(enc.encode("data: [DONE]\n\n"));
              controller.close();
              return;
            }
          } catch { /* skip */ }
        }
      }
      controller.enqueue(enc.encode("data: [DONE]\n\n"));
      controller.close();
    },
  });
}

// ── Main handler ─────────────────────────────────────────────────────────────
export async function POST(req: NextRequest) {
  const body = (await req.json()) as ReqBody;

  const stream = body.provider === "hosted"
    ? await streamEngineer0(body)
    : await streamOllama(body);

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
