"use client";

import { useCallback, useEffect, useState } from "react";

/** Fetch a JSON endpoint and refresh it every `refreshMs` (0 = once). */
export function useApi<T>(path: string, refreshMs = 30_000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await fetch(path, { cache: "no-store" });
      if (r.status === 401) {
        window.location.href = "/login";
        return;
      }
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setData((await r.json()) as T);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [path]);
  useEffect(() => {
    load();
    if (!refreshMs) return;
    const t = setInterval(load, refreshMs);
    return () => clearInterval(t);
  }, [load, refreshMs]);
  return { data, error, reload: load };
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function rupees(v: number | null | undefined): string {
  return v == null ? "–" : `₹${inr.format(v)}`;
}

export function signedRupees(v: number | null | undefined): string {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}₹${inr.format(Math.abs(v))}`;
}

export function num(v: number | null | undefined, digits = 2): string {
  return v == null ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: digits });
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export type Book = {
  days: { day: string; signal_date: string; cash: number | null; open_pnl: number | null; equity: number | null;
    gross: number | null; n_long: number | null; n_short: number | null; trades: number; charges: number;
    blocked: number }[];
  cash: number | null;
  equity: number | null;
  day_pnl: number | null;
  total_pnl: number | null;
  gross: number | null;
  positions: { symbol: string; qty: number; avg_price: number; lot_size: number; expiry: string; opened: string }[];
  trades: { ts: string; day: string; symbol: string; side: string; qty: number; price: number; charges: number;
    reason: string; signal_date: string }[];
  events: { ts: string; kind: string; detail: string }[];
  kill: Kill;
};

export type Kill = { on: boolean; since?: string; reason?: string };
