"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import { type Book, rupees, useApi } from "@/lib/api";
import { Badge, Card, ErrorNote, PageTitle, Stat } from "@/components/ui";
import { ScoreBar } from "@/components/score-bar";
import { ScoreHistogram } from "@/components/score-histogram";
import { cn } from "@/lib/cn";

type Row = { rank: number; symbol: string; score: number; close: number; lot_size: number | null; fut_expiry: string | null };

function SignalList({ rows, held, max, side }: { rows: Row[]; held: Set<string>; max: number; side: "up" | "down" }) {
  if (!rows.length) return <p className="py-6 text-sm text-muted-foreground">No signals yet.</p>;
  return (
    <div className="-mx-2 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-medium text-muted-foreground">
            <th className="px-2 pb-2 font-medium">Rank</th>
            <th className="px-2 pb-2 font-medium">Symbol</th>
            <th className="px-2 pb-2 font-medium">Score</th>
            <th className="px-2 pb-2 text-right font-medium">Close</th>
            <th className="px-2 pb-2 text-right font-medium">Lot</th>
            <th className="px-2 pb-2 font-medium">Futures expiry</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="hover:bg-muted/60">
              <td className="rounded-l-md px-2 py-2">
                <span className={cn("inline-flex h-7 w-11 items-center justify-center rounded-md text-xs font-semibold tabular-nums",
                  side === "up" ? "bg-up/15 text-up" : "bg-down/15 text-down")}>{r.rank}</span>
              </td>
              <td className="whitespace-nowrap px-2 py-2">
                <span className="font-medium">{r.symbol}</span>
                {held.has(r.symbol) && <span className="ml-2"><Badge kind="brand">Held</Badge></span>}
              </td>
              <td className="px-2 py-2"><ScoreBar score={r.score} max={max} /></td>
              <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">{rupees(r.close)}</td>
              <td className="px-2 py-2 text-right tabular-nums">{r.lot_size ?? "–"}</td>
              <td className="whitespace-nowrap rounded-r-md px-2 py-2 tabular-nums text-muted-foreground">{r.fut_expiry ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SignalsPage() {
  const { data, error } = useApi<{ date: string | null; rows: Row[] }>("/api/signals", 300_000);
  const { data: book } = useApi<Book>("/api/book", 60_000);
  const rows = data?.rows ?? [];
  const held = new Set((book?.positions ?? []).map((p) => p.symbol));
  const max = Math.max(...rows.map((r) => Math.abs(r.score)), 0.0001);
  const top = rows.slice(0, 25);
  const bottom = rows.slice(-25).reverse();
  const positive = rows.filter((r) => r.score > 0).length;
  return (
    <>
      <PageTitle sub="The champion model's ranking for the next 5 sessions. Bars grow right (blue) for stocks expected to beat the rest, left (red) for those expected to lag.">
        Signals
      </PageTitle>
      <ErrorNote error={error} />
      <div className="mb-8 flex flex-wrap gap-x-12 gap-y-6">
        <Stat label="From the close of" value={data?.date ?? "–"} />
        <Stat label="Stocks ranked" value={rows.length ? rows.length.toLocaleString("en-IN") : "–"} />
        <Stat label="Expected to beat the rest" value={rows.length ? `${positive}` : "–"} tone={rows.length ? "pos" : undefined} />
        <Stat label="Held by the paper book" value={book ? `${held.size}` : "–"} />
      </div>
      <Card title="Score distribution" className="mb-5">
        <ScoreHistogram scores={rows.map((r) => r.score)} />
      </Card>
      <div className="grid gap-5 2xl:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><TrendingUp className="size-5 text-up" />Strongest</span>}>
          <SignalList rows={top} held={held} max={max} side="up" />
        </Card>
        <Card title={<span className="flex items-center gap-2"><TrendingDown className="size-5 text-down" />Weakest</span>}>
          <SignalList rows={bottom} held={held} max={max} side="down" />
        </Card>
      </div>
    </>
  );
}
