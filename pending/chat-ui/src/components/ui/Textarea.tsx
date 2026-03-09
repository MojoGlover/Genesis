"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-[44px] w-full resize-none rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-400/60 dark:border-zinc-800 dark:bg-zinc-950",
        className
      )}
      {...props}
    />
  );
}
