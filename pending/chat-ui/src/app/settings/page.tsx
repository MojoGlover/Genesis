"use client";

import * as React from "react";
import { loadSettings, saveSettings, defaultSettings, type UiSettings } from "@/lib/storage";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export default function SettingsPage() {
  const [s, setS] = React.useState<UiSettings>(() => loadSettings());

  React.useEffect(() => {
    saveSettings(s);
  }, [s]);

  return (
    <div className="space-y-3">
      <div>
        <div className="text-lg font-semibold">Settings</div>
        <div className="text-sm text-zinc-500 dark:text-zinc-400">
          UI settings are stored in localStorage (starter). Move to a real user profile later.
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <div className="text-sm font-medium">Provider</div>
            <select
              className="h-10 w-full rounded-xl border border-zinc-200 bg-white px-3 text-sm dark:border-zinc-800 dark:bg-zinc-950"
              value={s.provider}
              onChange={(e) => setS((p) => ({ ...p, provider: e.target.value as any }))}
            >
              <option value="local">local</option>
              <option value="hosted">hosted</option>
            </select>
          </div>

          <div className="space-y-1">
            <div className="text-sm font-medium">Model (default)</div>
            <Input value={s.model} onChange={(e) => setS((p) => ({ ...p, model: e.target.value }))} placeholder="e.g. llama3.1:8b" />
          </div>

          <label className="flex items-center justify-between gap-2 rounded-xl border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <span>Enable TTS replies</span>
            <input type="checkbox" checked={s.ttsEnabled} onChange={(e) => setS((p) => ({ ...p, ttsEnabled: e.target.checked }))} />
          </label>

          <div className="rounded-xl border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <div className="font-medium">STT Mode</div>
            <div className="mt-2 flex gap-2">
              {(["off", "push", "toggle"] as const).map((m) => (
                <Button key={m} size="sm" variant={s.sttMode === m ? "default" : "ghost"} onClick={() => setS((p) => ({ ...p, sttMode: m }))}>
                  {m}
                </Button>
              ))}
            </div>
            <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              This starter uses browser STT; if you add server STT later, this setting can switch behaviors.
            </div>
          </div>
        </div>

        <div className="mt-4 flex gap-2">
          <Button variant="ghost" onClick={() => setS(defaultSettings)}>
            Reset to defaults
          </Button>
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="font-semibold">Backend wiring</div>
        <div className="mt-2 text-zinc-600 dark:text-zinc-300">
          This starter ships with demo endpoints: <code>/api/models</code>, <code>/api/files</code>, <code>/api/chat</code>. Replace those with your
          gateway when ready.
        </div>
      </div>
    </div>
  );
}
