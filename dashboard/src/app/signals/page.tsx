"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Minus, Search, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { type Book, type Quality, pct, rupees, useApi } from "@/lib/api";
import { Badge, Card, Chips, ErrorNote, Input, Loading, PageTitle, Stat, SymbolLink } from "@/components/ui";
import { ScoreBar } from "@/components/score-bar";
import { ScoreHistogram } from "@/components/score-histogram";
import { HBars, PicksVsMarket, SignedBars } from "@/components/charts";
import { StarButton } from "@/components/star";
import { useWatchlist } from "@/lib/watchlist";
import { cn } from "@/lib/cn";

type Row = { rank: number; symbol: string; score: number; close: number; lot_size: number | null; fut_expiry: string | null;
  prev_rank: number | null; sector: string | null };
type Signals = { date: string | null; dates: string[]; prev_date: string | null; rows: Row[] };

function Change({ r, hasPrev }: { r: Row; hasPrev: boolean }) {
  if (!hasPrev) return null;
  if (r.prev_rank == null) return <Badge kind="brand"><Sparkles className="size-3" />new</Badge>;
  const d = r.prev_rank - r.rank;
  if (d === 0) return <span className="inline-flex items-center text-xs text-muted-foreground"><Minus className="size-3" /></span>;
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-xs font-medium tabular-nums", d > 0 ? "text-up" : "text-down")}
      title={`was #${r.prev_rank}`}>
      {d > 0 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}{Math.abs(d)}
    </span>
  );
}

function SignalList({ rows, held, max, side, hasPrev, fut }: { rows: Row[]; held: Set<string>; max: number; side: "up" | "down"; hasPrev: boolean; fut: boolean }) {
  if (!rows.length) return <p className="py-6 text-sm text-muted-foreground">Nothing to show.</p>;
  return (
    <div className="-mx-2 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="w-8 px-1 pb-2" />
            <th className="px-2 pb-2 font-medium">Rank</th>
            <th className="px-2 pb-2 font-medium">Change</th>
            <th className="px-2 pb-2 font-medium">Symbol</th>
            <th className="px-2 pb-2 font-medium">Score</th>
            <th className="px-2 pb-2 text-right font-medium">Close</th>
            <th className="px-2 pb-2 font-medium">Sector</th>
            {fut && <th className="px-2 pb-2 text-right font-medium">Lot</th>}
            {fut && <th className="px-2 pb-2 font-medium">Expiry</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="hover:bg-muted/60">
              <td className="rounded-l-md px-1 py-1.5"><StarButton symbol={r.symbol} /></td>
              <td className="px-2 py-1.5">
                <span className={cn("inline-flex h-7 w-12 items-center justify-center rounded-md text-xs font-semibold tabular-nums",
                  side === "up" ? "bg-up/15 text-up" : "bg-down/15 text-down")}>{r.rank}</span>
              </td>
              <td className="px-2 py-1.5"><Change r={r} hasPrev={hasPrev} /></td>
              <td className="whitespace-nowrap px-2 py-1.5">
                <SymbolLink symbol={r.symbol} />
                {held.has(r.symbol) && <span className="ml-2"><Badge kind="brand">Held</Badge></span>}
              </td>
              <td className="px-2 py-1.5"><ScoreBar score={r.score} max={max} /></td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{rupees(r.close)}</td>
              <td className={cn("max-w-44 truncate px-2 py-1.5 text-xs text-muted-foreground", !fut && "rounded-r-md")} title={r.sector ?? ""}>{r.sector ?? "–"}</td>
              {fut && <td className="px-2 py-1.5 text-right tabular-nums">{r.lot_size ?? "–"}</td>}
              {fut && <td className="whitespace-nowrap rounded-r-md px-2 py-1.5 tabular-nums text-muted-foreground">{r.fut_expiry ?? "–"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SignalsPage() {
  const [day, setDay] = useState("");
  const [view, setView] = useState<"top" | "watch" | "all">("top");
  const [q, setQ] = useState("");
  const { data, error, reload } = useApi<Signals>(`/api/signals${day ? `?date=${day}` : ""}`, 300_000);
  const { data: book } = useApi<Book>("/api/book", 120_000);
  const { data: quality } = useApi<Quality>("/api/signals/quality", 1_800_000);
  const watch = useWatchlist();
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const held = new Set((book?.positions ?? []).map((p) => p.symbol));
  const max = Math.max(...rows.map((r) => Math.abs(r.score)), 0.0001);
  const positive = rows.filter((r) => r.score > 0).length;
  const hasPrev = !!data?.prev_date;
  const fut = book?.vehicle === "fut";
  const newIn = rows.slice(0, 20).filter((r) => hasPrev && (r.prev_rank == null || r.prev_rank > 20)).length;
  const needle = q.trim().toUpperCase();
  const filtered = rows.filter((r) => (!needle || r.symbol.includes(needle)) && (view !== "watch" || watch.has(r.symbol)));
  const sectors = Object.entries(rows.slice(0, 20).reduce<Record<string, number>>((a, r) => {
    const k = r.sector ?? "Not in Nifty 500";
    a[k] = (a[k] ?? 0) + 1;
    return a;
  }, {})).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
  const qs = quality?.summary;
  const qdays = quality?.days ?? [];

  return (
    <>
      <PageTitle sub="The champion model's ranking for the next 5 sessions. Bars grow right (blue) for stocks expected to beat the rest, left (red) for those expected to lag.">
        Signals
      </PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      <div className="mb-6 flex flex-wrap items-end gap-x-10 gap-y-5">
        <label className="text-xs font-medium text-muted-foreground">
          From the close of
          <select value={data?.date ?? ""} onChange={(e) => setDay(e.target.value)}
            className="mt-1 block h-10 rounded-md border border-input bg-background px-3 text-base font-semibold text-foreground">
            {[...(data?.dates ?? [])].reverse().map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <Stat label="Stocks ranked" value={rows.length ? rows.length.toLocaleString("en-IN") : "–"} />
        <Stat label="Expected to beat the rest" value={rows.length ? `${positive}` : "–"} />
        <Stat label="New in the top 20" value={hasPrev ? `${newIn}` : "–"} sub={data?.prev_date ? `vs ${data.prev_date}` : undefined} />
        <Stat label="Held by the paper book" value={book ? `${held.size}` : "–"} />
      </div>
      {!data && !error ? <Loading rows={8} /> : (
        <div className="grid gap-5">
          <div className="grid gap-5 xl:grid-cols-3">
            <Card title="Score distribution" className="xl:col-span-2"><ScoreHistogram scores={rows.map((r) => r.score)} /></Card>
            <Card title="Sectors in the top 20"><HBars items={sectors.slice(0, 8)} format={(v) => `${v}`} height={24} /></Card>
          </div>

          <Card title="Did past picks work?" action={<span className="text-xs text-muted-foreground">next open → 5th close after each signal day</span>}>
            <div className="mb-5 grid grid-cols-2 gap-x-8 gap-y-4 md:grid-cols-4">
              <Stat label="Signal days scored" value={qs?.dates ?? "–"} />
              <Stat label={`Top ${quality?.k ?? ""} picks, avg 5-day`} value={pct(qs?.top_ret)} tone={qs?.top_ret != null ? (qs.top_ret >= 0 ? "pos" : "neg") : undefined}
                sub={qs?.market_ret != null ? `average stock ${pct(qs.market_ret)}` : undefined} />
              <Stat label="Picks beat the market" value={qs?.beat_rate != null ? pct(qs.beat_rate, 0, false) : "–"} sub="share of signal days" />
              <Stat label="Mean rank IC" value={qs?.mean_ic != null ? qs.mean_ic.toFixed(3) : "–"} sub="above 0 = ranking has skill" />
            </div>
            <div className="grid gap-6 xl:grid-cols-2">
              <div>
                <h3 className="mb-2 text-sm font-medium text-muted-foreground">Top picks vs the average stock</h3>
                <PicksVsMarket points={qdays.map((d) => ({ x: d.date, picks: d.top_ret, market: d.market_ret }))} />
              </div>
              <div>
                <h3 className="mb-2 text-sm font-medium text-muted-foreground">Rank IC per signal day (faded = 5-day window still open)</h3>
                <SignedBars name="Rank IC" format={(v) => v.toFixed(2)} points={qdays.map((d) => ({ x: d.date, y: d.ic, dim: !d.complete }))} />
              </div>
            </div>
          </Card>

          <div className="flex flex-wrap items-center gap-3">
            <Chips value={view} onChange={setView} options={[{ key: "top", label: "Strongest & weakest" }, { key: "watch", label: `Watchlist (${watch.list.length})` }, { key: "all", label: "All" }]} />
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input placeholder="Find a symbol" value={q} onChange={(e) => setQ(e.target.value)} className="h-9 w-48 pl-9 text-sm" />
            </div>
          </div>
          {view === "top" && !needle ? (
            <div className="grid gap-5 2xl:grid-cols-2">
              <Card title={<span className="flex items-center gap-2"><TrendingUp className="size-5 text-up" />Strongest</span>}>
                <SignalList rows={rows.slice(0, 25)} held={held} max={max} side="up" hasPrev={hasPrev} fut={fut} />
              </Card>
              <Card title={<span className="flex items-center gap-2"><TrendingDown className="size-5 text-down" />Weakest</span>}>
                <SignalList rows={rows.slice(-25).reverse()} held={held} max={max} side="down" hasPrev={hasPrev} fut={fut} />
              </Card>
            </div>
          ) : (
            <Card title={view === "watch" ? "Watchlist" : "All ranked stocks"}>
              {view === "watch" && !watch.list.length
                ? <p className="py-6 text-sm text-muted-foreground">Star a stock (☆) in any list to follow it here.</p>
                : <SignalList rows={filtered.slice(0, 300)} held={held} max={max} side="up" hasPrev={hasPrev} fut={fut} />}
              {filtered.length > 300 && <p className="mt-3 text-xs text-muted-foreground">Showing the first 300 of {filtered.length}. Search to narrow down.</p>}
            </Card>
          )}
        </div>
      )}
    </>
  );
}
