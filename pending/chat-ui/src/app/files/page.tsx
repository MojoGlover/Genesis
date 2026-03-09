"use client";

import * as React from "react";
import { Button } from "@/components/ui/Button";
import { uploadFiles } from "@/lib/api";
import type { UploadedFile } from "@/lib/types";

export default function FilesPage() {
  const [files, setFiles] = React.useState<UploadedFile[]>([]);
  const [busy, setBusy] = React.useState(false);

  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    if (!e.target.files) return;
    setBusy(true);
    try {
      const uploaded = await uploadFiles(Array.from(e.target.files));
      setFiles((prev) => [...uploaded, ...prev]);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="text-lg font-semibold">Files</div>
        <div className="text-sm text-zinc-500 dark:text-zinc-400">
          Basic file upload library view. Backend stores metadata in-memory (starter). Wire to your real file store later.
        </div>
      </div>

      <div className="rounded-2xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center gap-2">
          <input type="file" multiple onChange={pick} />
          {busy ? <span className="text-sm text-zinc-500">Uploading…</span> : null}
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        {files.map((f) => (
          <div key={f.file_id} className="rounded-2xl border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="font-medium">{f.name}</div>
            <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{f.mime}</div>
            <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{Math.round(f.size / 1024)} KB</div>
            <div className="mt-2 text-xs opacity-70">id: {f.file_id}</div>
          </div>
        ))}
        {!files.length ? <div className="text-sm text-zinc-500">No files uploaded yet.</div> : null}
      </div>
    </div>
  );
}
