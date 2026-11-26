"use client";

import { type Book, rupees, signedRupees, useApi, when } from "@/lib/api";
import { Card, ErrorNote, PageTitle, Stat, Table, tone } from "@/components/ui";
import { EquityChart } from "@/components/equity-chart";
import { KillSwitch } from "@/components/kill-switch";

export default function Overview() {
  const { data, error, reload } = useApi<Book>("/api/book");
  const marked = (data?.days ?? []).filter((d) => d.equity != null).map((d) => ({ day: d.day, equity: d.equity as number }));
  const last = data?.days.at(-1);
  return (
    <>
      <PageTitle sub="Live paper trading of the champion futures book. Fills are simulated on live prices; no real orders.">
        Overview
      </PageTitle>
      <ErrorNote error={error} />
      <div className="mb-8 flex flex-wrap gap-x-12 gap-y-6">
        <Stat label="Equity" value={rupees(data?.equity)} />
        <Stat label="Today" value={signedRupees(data?.day_pnl)} tone={tone(data?.day_pnl)} />
        <Stat label="Since start" value={signedRupees(data?.total_pnl)} tone={tone(data?.total_pnl)} />
        <Stat label="Gross exposure" value={rupees(data?.gross)} />
        <Stat label="Positions" value={data ? `${data.positions.filter((p) => p.qty > 0).length} long · ${data.positions.filter((p) => p.qty < 0).length} short` : "–"} />
      </div>
      <div className="grid gap-5 xl:grid-cols-3">
        <Card title="Equity" className="xl:col-span-2"><EquityChart points={marked} /></Card>
        <Card title="Kill switch"><KillSwitch kill={data?.kill} onChange={reload} /></Card>
        <Card title="Last session" className="xl:col-span-3">
          <Table head={["Day", "Signals from", "Trades", "Charges", "Blocked", "Open P&L"]}
            rows={last ? [[last.day, last.signal_date, last.trades, rupees(last.charges), last.blocked, signedRupees(last.open_pnl)]] : []}
            empty="No paper session yet. The first runs at 09:20 IST after the Breeze login." />
          {data?.events.length ? (
            <p className="mt-4 text-sm text-muted-foreground">Latest event: {data.events[0].kind} · {data.events[0].detail} · {when(data.events[0].ts)}</p>
          ) : null}
        </Card>
      </div>
    </>
  );
}
