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
    <ul className="-mx-2">
      {rows.map((r) => (
        <li key={r.symbol} className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-muted/60">
          <span className={cn("inline-flex h-7 w-11 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums",
            side === "up" ? "bg-up/15 text-up" : "bg-down/15 text-down")}>{r.rank}</span>
          <span className="min-w-28 font-medium">{r.symbol}</span>
          <span className="w-16 shrink-0">{held.has(r.symbol) && <Badge kind="brand">Held</Badge>}</span>
          <ScoreBar score={r.score} max={max} />
          <span className="ml-auto hidden text-sm tabular-nums text-muted-foreground sm:block">{rupees(r.close)}</span>
        </li>
      ))}
    </ul>
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
      <div className="grid gap-5 xl:grid-cols-2">
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
