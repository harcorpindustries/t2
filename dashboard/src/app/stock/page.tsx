"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ExternalLink } from "lucide-react";
import { num, pct, rupees, signedRupees, useApi, when } from "@/lib/api";
import { Badge, Card, ErrorNote, Loading, PageTitle, Stat, Table, tone } from "@/components/ui";
import { type Candle, CandleChart, RankChart } from "@/components/charts";
import { StarButton } from "@/components/star";

type StockData = {
  symbol: string;
  sector: string | null;
  candles: Candle[];
  scores: { date: string; rank: number; score: number; of: number }[];
  position: { qty: number; avg_price: number; opened: string } | null;
  trades: { ts: string; day: string; side: string; qty: number; price: number; charges: number; reason: string }[];
  news: { id: string; title: string | null; link: string; source: string; published_at: string | null; first_seen_at: string; category: string; tone: number }[];
};

function Stock() {
  const symbol = (useSearchParams().get("s") ?? "").toUpperCase();
  const { data, error, reload } = useApi<StockData>(symbol ? `/api/stock/${encodeURIComponent(symbol)}` : null, 300_000);
  if (!symbol) return <PageTitle sub="Open a stock from any table, or press ⌘K and type its symbol.">Stock</PageTitle>;
  const c = data?.candles ?? [];
  const last = c.at(-1);
  const prev = c.at(-2);
  const chg = last && prev ? last.close / prev.close - 1 : null;
  const yearAgo = c[0];
  const latest = data?.scores.at(-1);
  const pos = data?.position;
  return (
    <>
      <PageTitle sub={data?.sector ?? (data ? "Industry not listed (outside the Nifty 500)" : "")}>
        <span className="inline-flex items-center gap-2">{symbol}<StarButton symbol={symbol} /></span>
      </PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      {!data && !error ? <Loading rows={8} /> : data && (
        <div className="grid gap-5">
          <div className="flex flex-wrap gap-x-10 gap-y-5">
            <Stat label={`Close ${last?.date ?? ""}`} value={rupees(last?.close)} sub={chg != null ? `${pct(chg)} on the day` : undefined} tone={tone(chg)} />
            <Stat label="Since first bar" value={last && yearAgo ? pct(last.close / yearAgo.close - 1) : "–"} sub={yearAgo ? `from ${yearAgo.date}` : undefined} />
            <Stat label="Model rank" value={latest ? `#${latest.rank}` : "–"} sub={latest ? `of ${latest.of} on ${latest.date}` : "not ranked"} />
            <Stat label="Score" value={latest ? latest.score.toFixed(3) : "–"} tone={latest ? tone(latest.score) : undefined} />
            <Stat label="Paper position" value={pos ? `${num(pos.qty, 0)} sh` : "None"}
              sub={pos && last ? `avg ${rupees(pos.avg_price)} · ${signedRupees(pos.qty * (last.close - pos.avg_price))}` : undefined} />
          </div>
          <Card title="Daily price">
            <CandleChart candles={c} marks={data.trades.map((t) => ({ date: t.day, price: t.price, side: t.side }))} />
          </Card>
          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Model rank over time"><RankChart points={data.scores} /></Card>
            <Card title="Paper trades">
              <Table head={["Time", "Side", "Qty", "Price", "Charges", "Reason"]}
                rows={data.trades.map((t) => [when(t.ts), <Badge key="s" kind={t.side === "buy" ? "up" : "down"}>{t.side}</Badge>,
                  num(t.qty, 0), rupees(t.price), rupees(t.charges), t.reason])} empty="Never traded by the paper book." />
            </Card>
          </div>
          <Card title="News and filings">
            {!data.news.length ? <p className="py-6 text-sm text-muted-foreground">No tagged news yet.</p> : (
              <ul className="space-y-1">
                {data.news.map((n) => (
                  <li key={n.id} className="flex items-start gap-3 rounded-lg px-2 py-2 hover:bg-muted/40">
                    <span className="mt-1.5 w-24 shrink-0 text-xs tabular-nums text-muted-foreground">{when(n.published_at ?? n.first_seen_at).split(",")[0]}</span>
                    <a href={n.link} target="_blank" rel="noreferrer noopener" className="group min-w-0 flex-1 text-sm">
                      <span className="group-hover:underline">{n.title ?? n.link}</span>
                      <ExternalLink className="ml-1.5 inline size-3 text-muted-foreground" />
                      <span className="ml-2 text-xs text-muted-foreground">{n.source.replace(/_/g, " ")}</span>
                    </a>
                    {n.tone !== 0 && <Badge kind={n.tone > 0 ? "up" : "down"}>{n.tone > 0 ? "positive" : "negative"}</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </>
  );
}

export default function StockPage() {
  return <Suspense fallback={<Loading rows={8} />}><Stock /></Suspense>;
}
