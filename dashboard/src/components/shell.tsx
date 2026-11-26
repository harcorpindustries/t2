"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import {
  CircleDot, Menu, MoonStar, OctagonX, PanelLeft, Pause, Play, RefreshCw, Search, LogOut, TrendingUp,
} from "lucide-react";
import { NAV, Sidebar, chromeless } from "@/components/nav";
import { Toasts } from "@/components/toast";
import { useDark } from "@/components/theme";
import { RefreshContext, type Kill, type BreezeStatus, useApi } from "@/lib/api";
import { duration, marketStatus } from "@/lib/market";
import { cn } from "@/lib/cn";

type Ping = { kill: Kill; breeze: BreezeStatus; server_time: string };

const typing = (e: KeyboardEvent) => {
  const el = e.target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
};

/** Everything around a page: sidebar, top bar, command palette, keyboard shortcuts, toasts, auto-refresh. */
export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [paused, setPaused] = useState(false);
  const [tick, setTick] = useState(0);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const touch = useCallback(() => setLastUpdated(Date.now()), []);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  useEffect(() => {
    setCollapsed(localStorage.getItem("t2-sidebar") === "collapsed");
    setPaused(localStorage.getItem("t2-refresh") === "paused");
  }, []);
  const toggleSidebar = useCallback(() => {
    setCollapsed((c) => {
      localStorage.setItem("t2-sidebar", c ? "open" : "collapsed");
      return !c;
    });
  }, []);
  const togglePause = useCallback(() => {
    setPaused((p) => {
      localStorage.setItem("t2-refresh", p ? "on" : "paused");
      return !p;
    });
  }, []);

  // keyboard: ⌘K palette, ⌘B sidebar, "g" then a letter to jump, "/" search
  const pendingG = useRef(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
        return;
      }
      if (mod && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleSidebar();
        return;
      }
      if (typing(e) || mod || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        setPalette(true);
        return;
      }
      if (e.key === "g") {
        pendingG.current = Date.now();
        return;
      }
      if (Date.now() - pendingG.current < 1200) {
        const item = NAV.find((n) => n.key === e.key);
        pendingG.current = 0;
        if (item) router.push(item.href);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, toggleSidebar]);

  const refresh = useMemo(() => ({ paused, tick, lastUpdated, touch }), [paused, tick, lastUpdated, touch]);

  if (chromeless(path)) {
    return <RefreshContext.Provider value={refresh}><Toasts><main className="min-h-screen p-6">{children}</main></Toasts></RefreshContext.Provider>;
  }
  return (
    <RefreshContext.Provider value={refresh}>
      <Toasts>
        <div className="md:flex">
          <Sidebar collapsed={collapsed} onToggle={toggleSidebar} mobileOpen={mobileOpen} onClose={closeMobile} />
          <div className="min-w-0 flex-1">
            <TopBar onMenu={() => setMobileOpen(true)} onSearch={() => setPalette(true)} paused={paused}
              onPause={togglePause} onRefresh={() => setTick((t) => t + 1)} lastUpdated={lastUpdated} />
            <main className="mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">{children}</main>
          </div>
        </div>
        <Palette open={palette} onClose={() => setPalette(false)} onToggleSidebar={toggleSidebar} />
      </Toasts>
    </RefreshContext.Provider>
  );
}

function useNow(everyMs: number) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), everyMs);
    return () => clearInterval(t);
  }, [everyMs]);
  return now;
}

function Pill({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-xs font-medium", className)}>
      {children}
    </span>
  );
}

function TopBar({ onMenu, onSearch, paused, onPause, onRefresh, lastUpdated }: {
  onMenu: () => void; onSearch: () => void; paused: boolean; onPause: () => void; onRefresh: () => void;
  lastUpdated: number | null;
}) {
  const now = useNow(15_000);
  const { data } = useApi<Ping>("/api/ping", 60_000);
  const m = now ? marketStatus(now) : null;
  const ago = now && lastUpdated ? Math.max(0, Math.round((now.getTime() - lastUpdated) / 1000)) : null;
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 bg-background/85 px-3 backdrop-blur sm:px-6 lg:px-8">
      <button type="button" onClick={onMenu} aria-label="Open menu" className="rounded-md p-2 hover:bg-muted md:hidden">
        <Menu className="size-5" />
      </button>
      <button type="button" onClick={onSearch}
        className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md bg-muted/70 px-3 text-sm text-muted-foreground hover:bg-muted sm:max-w-xs">
        <Search className="size-4 shrink-0" />
        <span className="truncate">Search stocks, pages…</span>
        <kbd className="ml-auto hidden rounded bg-background px-1.5 py-0.5 font-mono text-[11px] sm:inline">⌘K</kbd>
      </button>
      <div className="ml-auto flex items-center gap-1.5">
        {m && (
          <Pill title={`${m.label}; ${m.next} in ${duration(m.inMs)} (IST, weekdays; exchange holidays not shown)`}
            className={m.state === "open" ? "bg-good/15 text-good" : m.state === "pre-open" ? "bg-warn/15 text-warn" : "bg-muted text-muted-foreground"}>
            {m.state === "open" ? <TrendingUp className="size-3.5" /> : m.state === "pre-open" ? <CircleDot className="size-3.5" /> : <MoonStar className="size-3.5" />}
            <span>{m.label}</span>
            <span className="hidden opacity-80 lg:inline">· {m.next} in {duration(m.inMs)}</span>
          </Pill>
        )}
        {data && (
          <Pill title={data.breeze.valid_today ? "Breeze session saved today" : "Breeze login needed today"}
            className={data.breeze.valid_today ? "bg-good/15 text-good" : "bg-warn/15 text-warn"}>
            <span className={cn("size-2 rounded-full", data.breeze.valid_today ? "bg-good" : "bg-warn")} />
            <span className="hidden sm:inline">Breeze</span>
          </Pill>
        )}
        {data?.kill.on && (
          <Pill className="bg-down/15 text-down" title={data.kill.reason}><OctagonX className="size-3.5" /><span className="hidden sm:inline">Kill switch on</span></Pill>
        )}
        <span className="hidden px-2 text-xs tabular-nums text-muted-foreground xl:inline" title="Last data update in this tab">
          {ago == null ? "" : ago < 60 ? `updated ${ago}s ago` : `updated ${Math.round(ago / 60)}m ago`}
        </span>
        <button type="button" onClick={onRefresh} aria-label="Refresh now" title="Refresh now"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground">
          <RefreshCw className="size-4" />
        </button>
        <button type="button" onClick={onPause} aria-label={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
          title={paused ? "Auto-refresh paused" : "Auto-refresh on (every 30 s while the market is open)"}
          className={cn("rounded-md p-2 hover:bg-muted", paused ? "text-warn" : "text-muted-foreground hover:text-foreground")}>
          {paused ? <Play className="size-4" /> : <Pause className="size-4" />}
        </button>
      </div>
    </header>
  );
}

type Cmd = { id: string; label: string; hint?: string; icon?: ReactNode; run: () => void };

function Palette({ open, onClose, onToggleSidebar }: { open: boolean; onClose: () => void; onToggleSidebar: () => void }) {
  const router = useRouter();
  const { toggle: toggleTheme } = useDark();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const { data } = useApi<{ symbols: string[] }>(open ? "/api/symbols" : null, 0);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) {
      setQ("");
      setSel(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const cmds: Cmd[] = useMemo(() => {
    const go = (href: string) => () => router.push(href);
    const pages: Cmd[] = NAV.map((n) => ({ id: `p${n.href}`, label: n.label, hint: `g ${n.key}`, icon: <n.icon className="size-4" />, run: go(n.href) }));
    const actions: Cmd[] = [
      { id: "a-theme", label: "Toggle dark theme", icon: <MoonStar className="size-4" />, run: toggleTheme },
      { id: "a-side", label: "Collapse / expand sidebar", hint: "⌘B", icon: <PanelLeft className="size-4" />, run: onToggleSidebar },
      { id: "a-out", label: "Sign out", icon: <LogOut className="size-4" />, run: () => window.dispatchEvent(new Event("t2:signout")) },
    ];
    const needle = q.trim().toUpperCase();
    const stocks: Cmd[] = needle
      ? (data?.symbols ?? []).filter((s) => s.includes(needle)).sort((a, b) => Number(!a.startsWith(needle)) - Number(!b.startsWith(needle)))
        .slice(0, 8).map((s) => ({ id: `s${s}`, label: s, hint: "stock", icon: <TrendingUp className="size-4" />, run: go(`/stock?s=${encodeURIComponent(s)}`) }))
      : [];
    const match = (c: Cmd) => !needle || c.label.toUpperCase().includes(needle);
    const direct: Cmd[] = needle && /^[A-Z0-9&-]{2,20}$/.test(needle) && !stocks.some((s) => s.label === needle)
      ? [{ id: `d${needle}`, label: `Open ${needle}`, hint: "stock", icon: <Search className="size-4" />, run: go(`/stock?s=${encodeURIComponent(needle)}`) }]
      : [];
    return [...stocks, ...pages.filter(match), ...actions.filter(match), ...direct];
  }, [q, data, router, toggleTheme, onToggleSidebar]);

  if (!open) return null;
  const run = (c: Cmd | undefined) => {
    if (!c) return;
    onClose();
    c.run();
  };
  return createPortal(
    <div className="fixed inset-0 z-[1000] flex items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-lg overflow-hidden rounded-xl bg-card shadow-2xl ring-1 ring-foreground/10">
        <div className="flex items-center gap-3 px-4">
          <Search className="size-4 text-muted-foreground" />
          <input ref={inputRef} value={q} placeholder="Type a stock symbol, page or action…"
            onChange={(e) => { setQ(e.target.value); setSel(0); }}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, cmds.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
              else if (e.key === "Enter") run(cmds[sel]);
            }}
            className="h-14 flex-1 bg-transparent text-base outline-none" />
          <kbd className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">Esc</kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto border-t border-border p-2">
          {cmds.map((c, i) => (
            <li key={c.id}>
              <button type="button" onMouseEnter={() => setSel(i)} onClick={() => run(c)}
                className={cn("flex h-10 w-full items-center gap-3 rounded-md px-3 text-left text-sm", i === sel ? "bg-brand/15 text-brand" : "hover:bg-muted")}>
                <span className="text-muted-foreground">{c.icon}</span>
                <span className="flex-1">{c.label}</span>
                {c.hint && <span className="font-mono text-[11px] text-muted-foreground">{c.hint}</span>}
              </button>
            </li>
          ))}
          {!cmds.length && <li className="px-3 py-6 text-center text-sm text-muted-foreground">No match.</li>}
        </ul>
        <p className="border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
          ↑↓ to move · Enter to open · <span className="font-mono">g</span> then a letter jumps to a page · <span className="font-mono">/</span> opens this
        </p>
      </div>
    </div>,
    document.body,
  );
}
