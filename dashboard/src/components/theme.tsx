"use client";

import { useEffect, useState } from "react";
import { ThemeProvider, useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/cn";

/** Dark by default; the choice is remembered per browser. */
export function Themes({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
      {children}
    </ThemeProvider>
  );
}

export function useDark() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const dark = !mounted || resolvedTheme !== "light";
  return { dark, toggle: () => setTheme(dark ? "light" : "dark") };
}

/** "Dark theme" with an on/off switch. Compact (collapsed sidebar): one icon button with a hover label. */
export function ThemeToggle({ compact }: { compact?: boolean }) {
  const { dark, toggle } = useDark();
  if (compact) {
    return (
      <button type="button" role="switch" aria-checked={dark} aria-label="Dark theme" onClick={toggle}
        className="group relative flex h-11 w-full items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground">
        {dark ? <Moon className="size-[18px]" /> : <Sun className="size-[18px]" />}
        <span role="tooltip" className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background opacity-0 shadow-md transition-opacity group-hover:opacity-100">
          Dark theme: {dark ? "on" : "off"}
        </span>
      </button>
    );
  }
  return (
    <button type="button" role="switch" aria-checked={dark} onClick={toggle}
      className="flex h-11 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
      <Moon className="size-[18px]" />
      <span className="flex-1 text-left">Dark theme</span>
      <span className={cn("relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
        dark ? "bg-brand" : "bg-input")}>
        <span className={cn("inline-block size-5 rounded-full bg-background shadow transition-transform",
          dark ? "translate-x-[22px]" : "translate-x-0.5")} />
      </span>
    </button>
  );
}
