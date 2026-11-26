"use client";

import { useEffect, useState } from "react";
import { ThemeProvider, useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";

/** Dark by default; the choice is remembered per browser. */
export function Themes({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
      {children}
    </ThemeProvider>
  );
}

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const dark = !mounted || resolvedTheme !== "light";
  return (
    <button type="button" onClick={() => setTheme(dark ? "light" : "dark")} aria-label="Switch theme"
      className="flex h-11 items-center gap-3 rounded-full px-4 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
      {dark ? "Light theme" : "Dark theme"}
    </button>
  );
}
