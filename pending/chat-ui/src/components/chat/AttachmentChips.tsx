"use client";

import * as React from "react";
import type { UploadedFile } from "@/lib/types";
import { Button } from "@/components/ui/Button";

export function AttachmentChips({
  files,
  onRemove
}: {
  files: UploadedFile[];
  onRemove: (file_id: string) => void;
}) {
  if (!files.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {files.map((f) => (
        <div key={f.file_id} className="flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs dark:border-zinc-800 dark:bg-zinc-950">
          <div className="max-w-[180px] truncate">
            <div className="font-medium">{f.name}</div>
            <div className="text-[11px] opacity-70">{Math.round(f.size / 1024)} KB</div>
          </div>
          <Button size="icon" variant="ghost" onClick={() => onRemove(f.file_id)} aria-label="Remove attachment">
            ✕
          </Button>
        </div>
      ))}
    </div>
  );
}
