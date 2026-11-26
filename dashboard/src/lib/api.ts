"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { marketStatus } from "@/lib/market";

/** Auto-refresh setting shared by every page (top bar: pause / resume). */
export const RefreshContext = createContext<{ paused: boolean; tick: number; lastUpdated: number | null;
  touch: () => void }>({ paused: false, tick: 0, lastUpdated: null, touch: () => {} });

/** Fetch a JSON endpoint and refresh it every `refreshMs` (0 = once). While the market is open, refreshes at
 *  least every 30 s; paused from the top bar = no automatic refresh at all. */
export function useApi<T>(path: string | null, refreshMs = 60_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { paused, tick, touch } = useContext(RefreshContext);
  const touchRef = useRef(touch);
  touchRef.current = touch;
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const r = await fetch(path, { cache: "no-store" });
      if (r.status === 401) {
        window.location.href = "/login";
        return;
      }
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        throw new Error(body?.detail ?? `${r.status} ${r.statusText}`);
      }
      setData((await r.json()) as T);
      setError(null);
      touchRef.current();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setLoading(true);
    load();
  }, [load, tick]);
  useEffect(() => {
    if (!refreshMs || paused) return;
    const every = marketStatus().state === "open" ? Math.min(refreshMs, 30_000) : refreshMs;
    const t = setInterval(load, every);
    return () => clearInterval(t);
  }, [load, refreshMs, paused]);
  return { data, error, loading, reload: load };
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) {
    window.location.href = "/login";
    throw new Error("signed out");
  }
  if (!r.ok) {
    const b = await r.json().catch(() => null);
    throw new Error(b?.detail ?? `${r.status}`);
  }
  return (await r.json()) as T;
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** Indian grouping: ₹1,23,456. */
export function rupees(v: number | null | undefined): string {
  return v == null ? "–" : `${v < 0 ? "−" : ""}₹${inr.format(Math.abs(v))}`;
}

export function signedRupees(v: number | null | undefined): string {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}₹${inr.format(Math.abs(v))}`;
}

/** Short form for tiles and axes: ₹52.3K, ₹1.25L, ₹3.4Cr. */
export function compactRupees(v: number | null | undefined): string {
  if (v == null) return "–";
  const a = Math.abs(v);
  const s = v < 0 ? "−" : "";
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)}L`;
  if (a >= 1e3) return `${s}₹${(a / 1e3).toFixed(1)}K`;
  return `${s}₹${a.toFixed(0)}`;
}

export function pct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v == null || Number.isNaN(v)) return "–";
  const x = v * 100;
  return `${signed && x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 2): string {
  return v == null ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: digits });
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function bytes(v: number | null | undefined): string {
  if (v == null) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let x = v;
  while (x >= 1024 && i < u.length - 1) {
    x /= 1024;
    i += 1;
  }
  return `${x.toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function toCsv(head: string[], rows: (string | number | null | undefined)[][]): string {
  const cell = (v: string | number | null | undefined) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [head, ...rows].map((r) => r.map(cell).join(",")).join("\n");
}

export function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export type Kill = { on: boolean; since?: string; reason?: string; flatten?: boolean };

export type Day = { day: string; signal_date: string; cash: number | null; open_pnl: number | null;
  equity: number | null; gross: number | null; n_long: number | null; n_short: number | null; trades: number;
  charges: number; blocked: number };

export type Position = { symbol: string; qty: number; avg_price: number; lot_size: number; expiry: string | null;
  opened: string; last: number | null; value: number; pnl: number | null; pnl_pct: number | null;
  since: string | null; days_held: number | null; rank: number | null; exit_k: number | null;
  sector: string | null };

export type Breakdown = { brokerage: number; stt: number; exchange: number; sebi: number; stamp: number; gst: number;
  dp: number; total: number };

export type Trade = { ts: string; day: string; symbol: string; side: string; qty: number; price: number;
  charges: number; reason: string; signal_date: string; breakdown: Breakdown | null };

export type Trip = { symbol: string; side: string; opened: string; closed: string; qty: number; entry: number;
  exit: number; pnl: number; ret: number; days: number };

export type Perf = { capital: number; equity: number; total_return: number | null; days: number;
  sharpe: number | null; volatility: number | null; max_drawdown: number; best_day: number | null;
  worst_day: number | null; up_days: number; down_days: number; charges: number; cost_drag: number | null;
  avg_exposure: number | null };

export type TradeStats = { closed: number; win_rate: number | null; avg_win: number | null; avg_loss: number | null;
  profit_factor: number | null; realized: number; avg_days: number | null };

export type Event = { ts: string; kind: string; detail: string };

export type Book = {
  days: Day[];
  cash: number | null;
  capital: number | null;
  vehicle: string;
  equity: number | null;
  day_pnl: number | null;
  total_pnl: number | null;
  gross: number | null;
  positions: Position[];
  trades: Trade[];
  round_trips: Trip[];
  stats: Perf | null;
  trade_stats: TradeStats;
  drawdown: { day: string; dd: number }[];
  events: Event[];
  kill: Kill;
};

export type BreezeStatus = { has_session: boolean; saved_at: string | null; valid_today: boolean };

export type Quality = {
  k: number;
  days: { date: string; ic: number; top_ret: number; market_ret: number; top_hits: number; complete: boolean; sessions: number }[];
  summary: { dates: number; mean_ic: number | null; top_ret: number | null; market_ret: number | null; beat_rate: number | null };
};
