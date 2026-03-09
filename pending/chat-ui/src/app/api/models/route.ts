import { NextRequest } from "next/server";

export const runtime = "nodejs";

const OLLAMA_BASE = "http://localhost:11434";

// Cloud models available as fallback
const HOSTED = [
  { id: "engineer0", label: "Engineer0 (local agent)" },
  { id: "claude-haiku-4-5", label: "Claude Haiku (cloud)" },
  { id: "gpt-4o-mini", label: "GPT-4o Mini (cloud)" },
];

export async function GET(req: NextRequest) {
  const provider = req.nextUrl.searchParams.get("provider") ?? "local";

  if (provider === "hosted") {
    return Response.json({ models: HOSTED });
  }

  // Fetch live model list from Ollama
  try {
    const res = await fetch(`${OLLAMA_BASE}/api/tags`, { cache: "no-store" });
    const data = await res.json();
    const models = (data.models ?? []).map((m: { name: string }) => ({
      id: m.name,
      label: m.name,
    }));
    return Response.json({ models });
  } catch {
    return Response.json({ models: [{ id: "blackzero:latest", label: "blackzero (offline?)" }] });
  }
}
