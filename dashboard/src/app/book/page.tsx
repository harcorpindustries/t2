"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { type Book, num, rupees, signedRupees, useApi, when } from "@/lib/api";
import { Badge, Card, ErrorNote, PageTitle, Table } from "@/components/ui";

export default function BookPage() {
  const { data, error } = useApi<Book>("/api/book");
  return (
    <>
      <PageTitle sub="Stock futures held by the paper book, every simulated fill, and every risk decision.">Book</PageTitle>
      <ErrorNote error={error} />
      <div className="grid gap-5">
        <Card title="Positions">
          <Table head={["Symbol", "Side", "Qty", "Lots", "Avg price", "Expiry", "Since"]}
            rows={(data?.positions ?? []).map((p) => [
              <span key="s" className="font-medium">{p.symbol}</span>,
              p.qty > 0 ? <Badge key="b" kind="up"><ArrowUpRight className="size-3.5" />Long</Badge>
                : <Badge key="b" kind="down"><ArrowDownRight className="size-3.5" />Short</Badge>,
              num(Math.abs(p.qty), 0), num(Math.abs(p.qty) / (p.lot_size || 1), 0), rupees(p.avg_price), p.expiry, p.opened,
            ])} empty="No open positions." />
        </Card>
        <Card title="Daily record">
          <Table head={["Day", "Equity", "Open P&L", "Gross", "Long", "Short", "Trades", "Charges", "Blocked"]}
            rows={[...(data?.days ?? [])].reverse().map((d) => [d.day, rupees(d.equity), signedRupees(d.open_pnl),
              rupees(d.gross), d.n_long ?? "–", d.n_short ?? "–", d.trades, rupees(d.charges), d.blocked])} />
        </Card>
        <Card title="Trades">
          <Table head={["Time", "Symbol", "Side", "Qty", "Price", "Charges", "Reason", "Signals"]}
            rows={(data?.trades ?? []).map((t) => [when(t.ts), t.symbol, t.side, num(t.qty, 0), rupees(t.price),
              rupees(t.charges), t.reason, t.signal_date])} />
        </Card>
        <Card title="Risk and system events">
          <Table head={["Time", "Event", "Detail"]}
            rows={(data?.events ?? []).map((e) => [when(e.ts), e.kind, <span key="d" className="whitespace-normal">{e.detail}</span>])}
            empty="No events." />
        </Card>
      </div>
    </>
  );
}
