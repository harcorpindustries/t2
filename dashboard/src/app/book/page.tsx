"use client";

import { Fragment, useMemo, useState } from "react";
import { ArrowDownRight, ArrowUpRight, ChevronDown, ChevronRight, Download, Search } from "lucide-react";
import { type Book, compactRupees, download, num, pct, rupees, signedRupees, toCsv, useApi, when } from "@/lib/api";
import { Badge, Card, Chips, ErrorNote, Input, Loading, PageTitle, Stat, SymbolLink, Table, tone } from "@/components/ui";
import { EquityCurve, PnlCalendar, ShareBars } from "@/components/charts";
import { cn } from "@/lib/cn";

const BREAKDOWN: [string, string][] = [
  ["brokerage", "Brokerage"], ["stt", "STT"], ["exchange", "Exchange"], ["sebi", "SEBI"], ["stamp", "Stamp duty"],
  ["gst", "GST"], ["dp", "DP charge"],
];

export default function BookPage() {
  const { data, error, reload } = useApi<Book>("/api/book");
  const [q, setQ] = useState("");
  const [side, setSide] = useState<"all" | "buy" | "sell">("all");
  const [open, setOpen] = useState<number | null>(null);
  const [alloc, setAlloc] = useState<"stock" | "sector">("stock");

  const trades = useMemo(() => (data?.trades ?? []).filter((t) =>
    (side === "all" || t.side === side) && (!q || t.symbol.includes(q.toUpperCase()) || t.reason.includes(q.toLowerCase()))), [data, q, side]);
  const s = data?.stats;
  const ts = data?.trade_stats;
  const marked = (data?.days ?? []).filter((d) => d.equity != null);
  const daily = marked.map((d, i) => ({ day: d.day, pnl: (d.equity as number) - (i ? (marked[i - 1].equity as number) : (data?.capital ?? d.equity as number)) }));
  const bySector = Object.entries((data?.positions ?? []).reduce<Record<string, number>>((acc, p) => {
    const k = p.sector ?? "Other / not in Nifty 500";
    acc[k] = (acc[k] ?? 0) + p.value;
    return acc;
  }, {})).map(([name, value]) => ({ name, value }));
  const fut = data?.vehicle === "fut";

  function exportTrades() {
    download(`t2-trades-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(
      ["time", "day", "symbol", "side", "qty", "price", "charges", "brokerage", "stt", "exchange", "sebi", "stamp", "gst", "dp", "reason", "signals_from"],
      trades.map((t) => [t.ts, t.day, t.symbol, t.side, t.qty, t.price, t.charges, t.breakdown?.brokerage, t.breakdown?.stt,
        t.breakdown?.exchange, t.breakdown?.sebi, t.breakdown?.stamp, t.breakdown?.gst, t.breakdown?.dp, t.reason, t.signal_date])));
  }

  return (
    <>
      <PageTitle sub={fut ? "Stock futures held by the paper book, every simulated fill and its charges." : "Shares held by the paper book (cash delivery), every simulated fill and its charges."}>
        Book
      </PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      {!data && !error ? <Loading rows={6} /> : (
        <div className="grid gap-5">
          <Card title="Performance">
            <div className="grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Total return" value={pct(s?.total_return)} tone={tone(s?.total_return)} sub={signedRupees(data?.total_pnl)} />
              <Stat label="Sharpe (annual)" value={s?.sharpe != null ? s.sharpe.toFixed(2) : "–"} sub={`${s?.days ?? 0} marked days`} />
              <Stat label="Max drawdown" value={pct(s?.max_drawdown)} tone={s?.max_drawdown ? "neg" : undefined} />
              <Stat label="Best / worst day" value={<span className="text-lg">{pct(s?.best_day)} / {pct(s?.worst_day)}</span>} sub={`${s?.up_days ?? 0} up · ${s?.down_days ?? 0} down`} />
              <Stat label="Charges" value={rupees(s?.charges)} sub={s?.cost_drag != null ? `${pct(s.cost_drag, 2, false)} of capital` : undefined} />
              <Stat label="Avg exposure" value={s?.avg_exposure != null ? pct(s.avg_exposure, 0, false) : "–"} sub="of capital invested" />
              <Stat label="Closed trades" value={ts?.closed ?? 0} sub={ts?.avg_days != null ? `held ${ts.avg_days.toFixed(1)} days on average` : undefined} />
              <Stat label="Win rate" value={ts?.win_rate != null ? pct(ts.win_rate, 0, false) : "–"} />
              <Stat label="Avg win / loss" value={<span className="text-lg">{signedRupees(ts?.avg_win)} / {signedRupees(ts?.avg_loss)}</span>} />
              <Stat label="Profit factor" value={ts?.profit_factor != null ? ts.profit_factor.toFixed(2) : "–"} sub="gains ÷ losses" />
              <Stat label="Realized P&L" value={signedRupees(ts?.realized)} tone={tone(ts?.realized)} sub="after charges" />
            </div>
          </Card>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card title="Positions" className="xl:col-span-2">
              <Table head={["Symbol", "Side", "Qty", "Avg price", "Last", "Value", "P&L", "Days", "Rank today", ...(fut ? ["Expiry"] : [])]}
                rows={(data?.positions ?? []).map((p) => [
                  <SymbolLink key="s" symbol={p.symbol} />,
                  p.qty > 0 ? <Badge key="b" kind="up"><ArrowUpRight className="size-3.5" />Long</Badge>
                    : <Badge key="b" kind="down"><ArrowDownRight className="size-3.5" />Short</Badge>,
                  num(Math.abs(p.qty), 0), rupees(p.avg_price), rupees(p.last), compactRupees(p.value),
                  <span key="p" className={cn(p.pnl != null && (p.pnl >= 0 ? "text-up" : "text-down"))}>{signedRupees(p.pnl)} <span className="text-xs opacity-80">{pct(p.pnl_pct)}</span></span>,
                  p.days_held ?? "–",
                  p.rank != null ? (
                    <span key="r" title={`Exits if its rank falls below ${p.exit_k}`} className={cn(p.exit_k && p.rank > p.exit_k * 0.75 && "text-warn")}>
                      #{p.rank}<span className="text-xs text-muted-foreground"> / exit &gt; {p.exit_k}</span>
                    </span>
                  ) : "–",
                  ...(fut ? [p.expiry ?? "–"] : []),
                ])} empty="No open positions." />
            </Card>
            <Card title="Allocation" action={<Chips value={alloc} onChange={setAlloc} options={[{ key: "stock", label: "Stock" }, { key: "sector", label: "Sector" }]} />}>
              <ShareBars format={compactRupees} items={alloc === "stock"
                ? (data?.positions ?? []).map((p) => ({ name: p.symbol, value: p.value, href: `/stock?s=${p.symbol}` }))
                : bySector} />
            </Card>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Equity"><EquityCurve points={marked.map((d) => ({ day: d.day, equity: d.equity as number }))} /></Card>
            <Card title="Daily P&L calendar"><PnlCalendar days={daily} /></Card>
          </div>

          <Card title="Closed trades">
            <Table head={["Symbol", "Side", "Opened", "Closed", "Days", "Qty", "Entry", "Exit", "P&L after charges", "Return"]}
              rows={(data?.round_trips ?? []).map((t) => [
                <SymbolLink key="s" symbol={t.symbol} />, t.side, t.opened, t.closed, t.days, num(t.qty, 0), rupees(t.entry), rupees(t.exit),
                <span key="p" className={t.pnl >= 0 ? "text-up" : "text-down"}>{signedRupees(t.pnl)}</span>, pct(t.ret)])}
              empty="No position has been closed yet." />
          </Card>

          <Card title="Trade log" action={
            <button type="button" onClick={exportTrades} disabled={!trades.length}
              className="inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50">
              <Download className="size-4" />CSV
            </button>}>
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input placeholder="Symbol or reason" value={q} onChange={(e) => setQ(e.target.value)} className="h-9 w-52 pl-9 text-sm" />
              </div>
              <Chips value={side} onChange={setSide} options={[{ key: "all", label: "All" }, { key: "buy", label: "Buys" }, { key: "sell", label: "Sells" }]} />
              <span className="text-xs text-muted-foreground">{trades.length} trades · click a row for its charges</span>
            </div>
            {!trades.length ? <p className="py-6 text-sm text-muted-foreground">No trades yet.</p> : (
              <div className="-mx-2 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground">
                      {["", "Time", "Symbol", "Side", "Qty", "Price", "Value", "Charges", "Reason", "Signals"].map((h) => <th key={h} className="px-2 pb-2 font-medium">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <Fragment key={i}>
                        <tr onClick={() => setOpen(open === i ? null : i)} className="cursor-pointer hover:bg-muted/60">
                          <td className="rounded-l-md px-2 py-2.5 text-muted-foreground">{open === i ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</td>
                          <td className="whitespace-nowrap px-2 py-2.5 tabular-nums">{when(t.ts)}</td>
                          <td className="px-2 py-2.5"><SymbolLink symbol={t.symbol} /></td>
                          <td className="px-2 py-2.5"><Badge kind={t.side === "buy" ? "up" : "down"}>{t.side}</Badge></td>
                          <td className="px-2 py-2.5 tabular-nums">{num(t.qty, 0)}</td>
                          <td className="px-2 py-2.5 tabular-nums">{rupees(t.price)}</td>
                          <td className="px-2 py-2.5 tabular-nums">{rupees(t.qty * t.price)}</td>
                          <td className="px-2 py-2.5 tabular-nums">{rupees(t.charges)}</td>
                          <td className="px-2 py-2.5">{t.reason}</td>
                          <td className="rounded-r-md px-2 py-2.5 tabular-nums text-muted-foreground">{t.signal_date}</td>
                        </tr>
                        {open === i && (
                          <tr>
                            <td />
                            <td colSpan={9} className="px-2 pb-4">
                              {t.breakdown ? (
                                <div className="flex flex-wrap gap-x-6 gap-y-2 rounded-lg bg-muted/50 px-4 py-3 text-xs">
                                  {BREAKDOWN.map(([k, label]) => (
                                    <span key={k}><span className="text-muted-foreground">{label}</span> <span className="font-medium tabular-nums">₹{(t.breakdown as unknown as Record<string, number>)[k].toFixed(2)}</span></span>
                                  ))}
                                  <span><span className="text-muted-foreground">Total</span> <span className="font-semibold tabular-nums">₹{t.breakdown.total.toFixed(2)}</span></span>
                                </div>
                              ) : <span className="text-xs text-muted-foreground">No breakdown.</span>}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Daily record">
            <Table head={["Day", "Signals from", "Equity", "Open P&L", "Invested", "Trades", "Charges", "Blocked"]}
              rows={[...(data?.days ?? [])].reverse().map((d) => [d.day, d.signal_date, rupees(d.equity), signedRupees(d.open_pnl),
                rupees(d.gross), d.trades, rupees(d.charges), d.blocked])} empty="No sessions yet." />
          </Card>
        </div>
      )}
    </>
  );
}
