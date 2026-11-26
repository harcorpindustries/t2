"use client";

import { useEffect, useState } from "react";
import { ThemeProvider, useTheme } from "next-themes";
import { Moon } from "lucide-react";
import { cn } from "@/lib/cn";

/** Dark by default; the choice is remembered per browser. */
export function Themes({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
      {children}
    </ThemeProvider>
  );
}

/** "Dark theme" with an on/off switch. The 44px row is the tap target; the switch itself is the visual. */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const dark = !mounted || resolvedTheme !== "light";
  return (
    <button type="button" role="switch" aria-checked={dark} onClick={() => setTheme(dark ? "light" : "dark")}
      className="flex h-11 w-full items-center gap-3 rounded-md px-4 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
      <Moon className="size-4" />
      <span className="flex-1 text-left">Dark theme</span>
      <span className={cn("relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
        dark ? "bg-brand" : "bg-input")}>
        <span className={cn("inline-block size-5 rounded-full bg-background shadow transition-transform",
          dark ? "translate-x-[22px]" : "translate-x-0.5")} />
      </span>
    </button>
  );
}
