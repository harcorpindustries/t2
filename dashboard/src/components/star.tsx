"use client";

import { Star } from "lucide-react";
import { useWatchlist } from "@/lib/watchlist";
import { cn } from "@/lib/cn";

export function StarButton({ symbol, className }: { symbol: string; className?: string }) {
  const { has, toggle } = useWatchlist();
  const on = has(symbol);
  return (
    <button type="button" onClick={() => toggle(symbol)} aria-pressed={on}
      aria-label={on ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`}
      title={on ? "On your watchlist" : "Add to watchlist"}
      className={cn("rounded-md p-1.5 hover:bg-muted", on ? "text-brand" : "text-muted-foreground/60 hover:text-foreground", className)}>
      <Star className="size-4" fill={on ? "currentColor" : "none"} />
    </button>
  );
}
