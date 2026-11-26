"use client";

import { useCallback, useEffect, useState } from "react";

const KEY = "t2-watchlist";

function read(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Starred stocks, kept in this browser. */
export function useWatchlist() {
  const [list, setList] = useState<string[]>([]);
  useEffect(() => {
    setList(read());
    const sync = () => setList(read());
    window.addEventListener("t2:watchlist", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("t2:watchlist", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const toggle = useCallback((s: string) => {
    const cur = read();
    const next = cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s];
    localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new Event("t2:watchlist"));
  }, []);
  return { list, has: (s: string) => list.includes(s), toggle };
}
