"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/Button";

type NavItem = { href: string; label: string };

const NAV: NavItem[] = [
  { href: "/chat", label: "Chat" },
  { href: "/files", label: "Files" },
  { href: "/voice", label: "Voice" },
  { href: "/settings", label: "Settings" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = React.useState(false);

  React.useEffect(() => setDrawerOpen(false), [pathname]);

  return (
    <div className="min-h-dvh">
      <div className="safe-top sticky top-0 z-40 border-b border-zinc-200 bg-zinc-50/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/60">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-3 py-2">
          <Button size="icon" variant="ghost" className="lg:hidden" aria-label="Open menu" onClick={() => setDrawerOpen(true)}>
            ☰
          </Button>
          <div className="flex items-baseline gap-2">
            <div className="text-sm font-semibold">PlugOps UI</div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400">Starter</div>
          </div>

          <div className="ml-auto hidden items-center gap-2 lg:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "rounded-xl px-3 py-2 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-900",
                  pathname === n.href && "bg-zinc-100 dark:bg-zinc-900"
                )}
              >
                {n.label}
              </Link>
            ))}
          </div>
        </div>
      </div>

      {/* Mobile / tablet drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawerOpen(false)} />
          <div className="absolute left-0 top-0 h-full w-[280px] bg-white p-3 shadow-xl dark:bg-zinc-950">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-semibold">Menu</div>
              <Button size="icon" variant="ghost" onClick={() => setDrawerOpen(false)} aria-label="Close menu">
                ✕
              </Button>
            </div>
            <div className="flex flex-col gap-1">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className={cn(
                    "rounded-xl px-3 py-2 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-900",
                    pathname === n.href && "bg-zinc-100 dark:bg-zinc-900"
                  )}
                >
                  {n.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}

      <main className="mx-auto max-w-6xl px-3 py-4">{children}</main>
    </div>
  );
}
