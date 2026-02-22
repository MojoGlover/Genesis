"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "ghost" | "danger";
  size?: "sm" | "md" | "icon";
};

export function Button({ className, variant = "default", size = "md", ...props }: Props) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-xl font-medium transition focus:outline-none focus:ring-2 focus:ring-zinc-400/60 disabled:opacity-50 disabled:pointer-events-none",
        variant === "default" && "bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200",
        variant === "ghost" && "bg-transparent hover:bg-zinc-100 dark:hover:bg-zinc-900",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-500",
        size === "sm" && "h-9 px-3 text-sm",
        size === "md" && "h-10 px-4 text-sm",
        size === "icon" && "h-10 w-10",
        className
      )}
      {...props}
    />
  );
}
