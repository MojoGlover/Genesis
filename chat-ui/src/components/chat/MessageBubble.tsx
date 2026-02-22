"use client";

import * as React from "react";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/cn";

export function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[92%] rounded-2xl px-4 py-3 text-sm shadow-sm",
          isUser
            ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
            : "bg-white text-zinc-900 dark:bg-zinc-900 dark:text-zinc-100",
          "border border-zinc-200/70 dark:border-zinc-800/70"
        )}
      >
        {msg.attachments?.length ? (
          <div className="mb-2 flex flex-wrap gap-2">
            {msg.attachments.map((f) => (
              <div key={f.file_id} className="rounded-xl border border-zinc-200 px-2 py-1 text-xs dark:border-zinc-800">
                <div className="font-medium">{f.name}</div>
                <div className="text-[11px] opacity-70">{f.mime}</div>
              </div>
            ))}
          </div>
        ) : null}
        <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
      </div>
    </div>
  );
}
