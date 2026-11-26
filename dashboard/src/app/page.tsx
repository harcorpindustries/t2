"use client";

import { CheckCircle2, Circle, Clock, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { type Book, type BreezeStatus, compactRupees, pct, rupees, signedRupees, useApi, when } from "@/lib/api";
import { Card, ErrorNote, PageTitle, Tile, tone } from "@/components/ui";
import { type BenchPoint, DrawdownChart, EquityVsBench, Sparkline } from "@/components/charts";
import { KillSwitch } from "@/components/kill-switch";
import { BreezeLogin } from "@/components/breeze-login";
import { istNow } from "@/lib/market";
import { cn } from "@/lib/cn";

type Status = { timers: { unit: string; result: string | null }[]; freshness: { name: string; last: string }[] };
type Meta = { trained_on: string; data_last_date: string };
type Signals = { date: string | null };

const daysAgo = (iso: string | null | undefined) =>
  iso ? Math.floor((Date.now() - new Date(iso.slice(0, 10) + "T00:00:00Z").getTime()) / 86_400_000) : null;

type StepState = "done" | "wait" | "fail" | "skip";

function Step({ state, title, detail, at }: { state: StepState; title: string; detail: ReactNode; at: string }) {
  const Icon = state === "done" ? CheckCircle2 : state === "fail" ? XCircle : state === "wait" ? Clock : Circle;
  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <Icon className={cn("size-5 shrink-0", state === "done" && "text-good", state === "fail" && "text-down",
          state === "wait" && "text-muted-foreground", state === "skip" && "text-muted-foreground/50")} />
        <span className="mt-1 w-px flex-1 bg-border" />
      </div>
      <div className="pb-5">
        <div className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium">
          {title}<span className="text-xs font-normal tabular-nums text-muted-foreground">{at}</span>
        </div>
        <div className="text-sm text-muted-foreground">{detail}</div>
      </div>
    </li>
  );
}

function Check({ ok, label, detail }: { ok: boolean | null; label: string; detail: ReactNode }) {
  return (
    <li className="flex items-start gap-3 py-1.5">
      {ok == null ? <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        : ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-good" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-down" />}
      <div className="min-w-0 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground"> · {detail}</span>
      </div>
    </li>
  );
}

export default function Overview() {
  const { data, error, reload } = useApi<Book>("/api/book");
  const { data: bench } = useApi<{ points: BenchPoint[] }>("/api/benchmark", 600_000);
  const { data: breeze } = useApi<BreezeStatus>("/api/breeze/status", 60_000);
  const { data: status } = useApi<Status>("/api/status", 60_000);
  const { data: model } = useApi<Meta>("/api/model", 600_000);
  const { data: sig } = useApi<Signals>("/api/signals", 600_000);

  const loading = !data && !error;
  const marked = (data?.days ?? []).filter((d) => d.equity != null);
  const eqSeries = [data?.capital ?? 0, ...marked.map((d) => d.equity as number)].filter((x) => x > 0);
  const last = bench?.points.at(-1);
  const excess = last && last.nifty != null ? (last.t2 - last.nifty) / 100 : null;
  const longs = data?.positions.filter((p) => p.qty > 0).length ?? 0;
  const shorts = data?.positions.filter((p) => p.qty < 0).length ?? 0;
  const open = data?.positions.reduce((a, p) => a + (p.pnl ?? 0), 0);

  // today's timeline (IST)
  const ist = istNow();
  const today = ist.toISOString().slice(0, 10);
  const mins = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  const weekday = ist.getUTCDay() >= 1 && ist.getUTCDay() <= 5;
  const todayRow = data?.days.find((d) => d.day === today);
  const tradesToday = data?.trades.filter((t) => t.day === today) ?? [];
  const sigAge = daysAgo(sig?.date);
  const step = (done: boolean, dueMins: number): StepState => done ? "done" : !weekday ? "skip" : mins > dueMins + 60 ? "fail" : "wait";

  const failing = (status?.timers ?? []).filter((t) => t.result && t.result !== "success");
  const prices = status?.freshness.find((f) => f.name === "NSE daily prices");
  const modelAge = daysAgo(model?.trained_on);

  return (
    <>
      <PageTitle sub="Live paper trading of the champion book. Fills are simulated on live prices; no real orders are placed.">
        Overview
      </PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <Tile label="Equity" value={compactRupees(data?.equity ?? data?.capital)} loading={loading}
          note={data?.capital ? `started ${compactRupees(data.capital)}` : undefined}>
          <Sparkline values={eqSeries} />
        </Tile>
        <Tile label="Today" value={signedRupees(data?.day_pnl)} tone={tone(data?.day_pnl)} loading={loading}
          note={data?.day_pnl != null && data.capital ? pct(data.day_pnl / data.capital) : "no session yet"} />
        <Tile label="Total return" value={pct(data?.stats?.total_return)} tone={tone(data?.stats?.total_return)} loading={loading}
          note={signedRupees(data?.total_pnl)} />
        <Tile label="vs Nifty 50" value={excess == null ? "–" : `${excess >= 0 ? "+" : "−"}${Math.abs(excess * 100).toFixed(2)} pts`}
          tone={tone(excess)} loading={loading} note={last?.nifty != null ? `Nifty ${pct(last.nifty / 100 - 1)}` : "after the first session"} />
        <Tile label="Positions" value={`${longs + shorts}`} loading={loading}
          note={shorts ? `${longs} long · ${shorts} short` : `open P&L ${signedRupees(open)}`} />
        <Tile label="Cash free" value={compactRupees(data?.cash)} loading={loading}
          note={data?.cash != null && data.equity ? `${pct(data.cash / data.equity, 0, false)} of equity` : undefined} />
        <Tile label="Charges paid" value={rupees(data?.stats?.charges)} loading={loading}
          note={data?.stats?.cost_drag != null ? `${pct(data.stats.cost_drag, 2, false)} of capital` : undefined} />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card title="Equity vs the market" className="xl:col-span-2">
          <EquityVsBench points={bench?.points ?? []} />
          <h3 className="mb-2 mt-6 text-sm font-medium text-muted-foreground">Drawdown (fall from the best equity so far)</h3>
          <DrawdownChart points={data?.drawdown ?? []} />
        </Card>
        <div className="grid content-start gap-5">
          <Card title="Breeze"><BreezeLogin /></Card>
          <Card title="Kill switch"><KillSwitch kill={data?.kill} onChange={reload} /></Card>
        </div>

        <Card title="Today">
          <ol>
            <Step state={step(sigAge != null && sigAge <= 4, 7 * 60 + 45)} title="Signals published" at="07:45"
              detail={sig?.date ? `from the close of ${sig.date}` : "waiting for the morning run"} />
            <Step state={step(!!breeze?.valid_today, 9 * 60 + 20)} title="Breeze login" at="before 09:20"
              detail={breeze?.valid_today ? `done ${when(breeze.saved_at)}` : "tap 'Log in to Breeze'"} />
            <Step state={step(!!todayRow, 10 * 60 + 15)} title="Open run" at="09:20"
              detail={todayRow ? `${todayRow.trades} filled · ${todayRow.blocked} blocked · charges ${rupees(todayRow.charges)}` : "orders at the open (retried 09:40, 10:15)"} />
            <Step state={step(tradesToday.length > 0 || (todayRow != null && todayRow.trades === 0), 10 * 60 + 15)} title="Fills" at="09:20–10:15"
              detail={tradesToday.length ? tradesToday.map((t) => `${t.side} ${t.qty} ${t.symbol}`).join(" · ") : todayRow ? "nothing to change today" : "–"} />
            <Step state={step(todayRow?.equity != null, 15 * 60 + 35)} title="Close valuation" at="15:35"
              detail={todayRow?.equity != null ? `equity ${rupees(todayRow.equity)}` : "marks positions at the close"} />
          </ol>
        </Card>
        <Card title="Health">
          <ul>
            <Check ok={breeze ? breeze.valid_today : null} label="Breeze session" detail={breeze?.valid_today ? "saved today" : "login needed"} />
            <Check ok={sigAge == null ? null : sigAge <= 4} label="Signals" detail={sig?.date ? `latest ${sig.date}` : "–"} />
            <Check ok={modelAge == null ? null : modelAge <= 8} label="Model" detail={model ? `trained ${model.trained_on} (data to ${model.data_last_date})` : "–"} />
            <Check ok={prices ? (daysAgo(prices.last) ?? 99) <= 4 : null} label="Price data" detail={prices ? `to ${prices.last}` : "–"} />
            <Check ok={status ? failing.length === 0 : null} label="Server jobs"
              detail={status ? (failing.length ? `failing: ${failing.map((t) => t.unit.replace("t2-", "")).join(", ")}` : `${status.timers.length} jobs ok`) : "–"} />
            <Check ok={data ? !data.kill.on : null} label="Kill switch" detail={data?.kill.on ? `on: ${data.kill.reason}` : "off"} />
          </ul>
        </Card>
        <Card title="Latest events">
          {data?.events.length ? (
            <ul className="space-y-2.5 text-sm">
              {data.events.slice(0, 7).map((e, i) => (
                <li key={i} className="flex gap-3">
                  <span className="w-28 shrink-0 text-xs tabular-nums text-muted-foreground">{when(e.ts)}</span>
                  <span className="min-w-0"><span className="font-medium">{e.kind.replace(/_/g, " ")}</span>
                    <span className="text-muted-foreground"> · {e.detail}</span></span>
                </li>
              ))}
            </ul>
          ) : <p className="py-6 text-sm text-muted-foreground">No events yet.</p>}
        </Card>
      </div>
    </>
  );
}
