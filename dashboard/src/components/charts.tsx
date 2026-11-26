"use client";

import type { CSSProperties, ReactNode } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, LineChart, ReferenceDot, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { compactRupees, pct, rupees } from "@/lib/api";
import { cn } from "@/lib/cn";

/* Color roles (globals.css, validated for color-blind separation): brand = T2's own line, up/down = a diverging
   pair for gains and losses, muted foreground = reference series (benchmarks), always dashed so they are told
   apart without color. */

export const tooltipStyle: CSSProperties = {
  borderRadius: 8, border: "none", boxShadow: "0 4px 12px -2px rgb(0 0 0 / 0.25)", background: "var(--card)",
  color: "var(--foreground)", fontSize: 12,
};
const axis = { tickLine: false, axisLine: false, fontSize: 12, stroke: "var(--muted-foreground)" } as const;

export function Legend({ items }: { items: { label: string; color: string; dash?: boolean; dot?: boolean }[] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden><line x1="1" y1="4" x2="17" y2="4" stroke={i.color} strokeWidth="2"
            strokeDasharray={i.dot ? "1 4" : i.dash ? "4 3" : undefined} strokeLinecap="round" /></svg>
          {i.label}
        </span>
      ))}
    </div>
  );
}

function Wait({ children, h = "h-64" }: { children: ReactNode; h?: string }) {
  return <div className={cn("flex items-center justify-center text-center text-sm text-muted-foreground", h)}>{children}</div>;
}

/** Tiny trend line for a KPI tile (no axes; the tile states the number). */
export function Sparkline({ values, color = "var(--brand)" }: { values: number[]; color?: string }) {
  if (values.length < 2) return null;
  const data = values.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer>
      <LineChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <YAxis hide domain={["auto", "auto"]} />
        <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export type BenchPoint = { day: string; t2: number; nifty: number | null; market: number | null };

/** T2's equity against Nifty 50 and the average stock, all starting at 100. One axis, one unit. */
export function EquityVsBench({ points }: { points: BenchPoint[] }) {
  if (points.length < 2) return <Wait>The comparison appears after the first marked trading day.</Wait>;
  const hasNifty = points.some((p) => p.nifty != null);
  const hasMkt = points.some((p) => p.market != null);
  return (
    <>
      <Legend items={[{ label: "T2 paper book", color: "var(--brand)" },
        ...(hasNifty ? [{ label: "Nifty 50", color: "var(--muted-foreground)", dash: true }] : []),
        ...(hasMkt ? [{ label: "Average stock", color: "var(--muted-foreground)", dash: true, dot: true }] : [])]} />
      <div className="h-64 w-full">
        <ResponsiveContainer>
          <LineChart data={points} margin={{ left: 4, right: 12, top: 8, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="day" {...axis} minTickGap={32} />
            <YAxis {...axis} width={44} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(1)} />
            <ReferenceLine y={100} stroke="var(--border)" />
            <Tooltip contentStyle={tooltipStyle} formatter={(v, name) => [`${Number(v).toFixed(2)} (${pct(Number(v) / 100 - 1)})`, String(name)]} />
            <Line name="T2" type="monotone" dataKey="t2" stroke="var(--brand)" strokeWidth={2} dot={points.length < 20 ? { r: 4 } : false} />
            {hasNifty && <Line name="Nifty 50" type="monotone" dataKey="nifty" stroke="var(--muted-foreground)" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls />}
            {hasMkt && <Line name="Average stock" type="monotone" dataKey="market" stroke="var(--muted-foreground)" strokeOpacity={0.7} strokeWidth={2} strokeDasharray="1 4" strokeLinecap="round" dot={false} connectNulls />}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

export function EquityCurve({ points }: { points: { day: string; equity: number }[] }) {
  if (points.length < 2) return <Wait>The curve appears after two marked trading days.</Wait>;
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <AreaChart data={points} margin={{ left: 4, right: 12, top: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--brand)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--brand)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="day" {...axis} minTickGap={32} />
          <YAxis {...axis} width={64} domain={["auto", "auto"]} tickFormatter={(v: number) => compactRupees(v)} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => [rupees(Number(v)), "Equity"]} />
          <Area type="monotone" dataKey="equity" stroke="var(--brand)" strokeWidth={2} fill="url(#eq)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DrawdownChart({ points }: { points: { day: string; dd: number }[] }) {
  if (points.length < 2) return <Wait h="h-36">Drawdown shows after two marked days.</Wait>;
  return (
    <div className="h-36 w-full">
      <ResponsiveContainer>
        <AreaChart data={points} margin={{ left: 4, right: 12, top: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="day" {...axis} minTickGap={32} />
          <YAxis {...axis} width={44} domain={["auto", 0]} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => [pct(Number(v)), "Below peak"]} />
          <Area type="stepAfter" dataKey="dd" stroke="var(--down)" strokeWidth={2} fill="var(--down)" fillOpacity={0.15} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Daily P&L as a calendar (weeks across, Mon–Fri down). Blue = gain, red = loss, darker = larger. Hover for the figure. */
export function PnlCalendar({ days }: { days: { day: string; pnl: number }[] }) {
  if (!days.length) return <Wait h="h-32">Fills in as trading days are recorded.</Wait>;
  const byDay = new Map(days.map((d) => [d.day, d.pnl]));
  const max = Math.max(...days.map((d) => Math.abs(d.pnl)), 1);
  const first = new Date(`${days[0].day}T00:00:00Z`);
  const last = new Date(`${days[days.length - 1].day}T00:00:00Z`);
  const start = new Date(first);
  start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7)); // back to Monday
  const weeks: Date[][] = [];
  for (let d = new Date(start); d <= last; d.setUTCDate(d.getUTCDate() + 7)) {
    weeks.push(Array.from({ length: 5 }, (_, i) => new Date(d.getTime() + i * 86_400_000)));
  }
  const shown = weeks.slice(-30);
  return (
    <div className="overflow-x-auto">
      <div className="flex gap-1">
        <div className="mr-1 flex flex-col gap-1 text-[10px] leading-5 text-muted-foreground">
          {["Mon", "Tue", "Wed", "Thu", "Fri"].map((d) => <span key={d} className="h-5">{d}</span>)}
        </div>
        {shown.map((w, i) => (
          <div key={i} className="flex flex-col gap-1">
            {w.map((d) => {
              const key = d.toISOString().slice(0, 10);
              const v = byDay.get(key);
              const a = v == null ? 0 : 0.25 + 0.75 * Math.min(1, Math.abs(v) / max);
              return (
                <div key={key} title={v == null ? `${key}: no trading` : `${key}: ${rupees(v)}`}
                  className={cn("size-5 rounded-[3px]", v == null && "bg-muted/60")}
                  style={v == null ? undefined : { background: v >= 0 ? "var(--up)" : "var(--down)", opacity: v === 0 ? 0.25 : a }} />
              );
            })}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
        <span>Loss</span>
        {[1, 0.6, 0.3].map((o) => <span key={`d${o}`} className="size-3 rounded-[2px]" style={{ background: "var(--down)", opacity: o }} />)}
        <span className="size-3 rounded-[2px] bg-muted/60" />
        {[0.3, 0.6, 1].map((o) => <span key={`u${o}`} className="size-3 rounded-[2px]" style={{ background: "var(--up)", opacity: o }} />)}
        <span>Gain</span>
      </div>
    </div>
  );
}

/** Part of a whole as a ranked bar list (clearer than a donut for a handful of items). */
export function ShareBars({ items, format }: { items: { name: string; value: number; href?: string }[]; format?: (v: number) => string }) {
  const total = items.reduce((a, b) => a + b.value, 0);
  if (!items.length || total <= 0) return <Wait h="h-24">Nothing held.</Wait>;
  return (
    <ul className="space-y-3">
      {[...items].sort((a, b) => b.value - a.value).map((i) => (
        <li key={i.name}>
          <div className="mb-1 flex justify-between gap-3 text-sm">
            {i.href ? <a href={i.href} className="truncate font-medium hover:text-brand hover:underline">{i.name}</a> : <span className="truncate font-medium">{i.name}</span>}
            <span className="tabular-nums text-muted-foreground">{format ? format(i.value) : ""} · {pct(i.value / total, 1, false)}</span>
          </div>
          <div className="h-2 rounded-sm bg-muted"><div className="h-2 rounded-sm bg-brand" style={{ width: `${(i.value / total) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

export type Candle = { date: string; open: number; high: number; low: number; close: number; volume: number };
type ShapeProps = { x?: number; y?: number; width?: number; height?: number; payload?: Candle };

function CandleShape(p: ShapeProps) {
  const { x = 0, y = 0, width = 0, height = 0, payload } = p;
  if (!payload) return null;
  const { open, close, high, low } = payload;
  const span = high - low || 1;
  const toY = (v: number) => y + ((high - v) / span) * height;
  const up = close >= open;
  const color = up ? "var(--up)" : "var(--down)";
  const top = toY(Math.max(open, close));
  const bodyH = Math.max(1, Math.abs(toY(open) - toY(close)));
  const cx = x + width / 2;
  const bw = Math.max(1, width * 0.7);
  return (
    <g>
      <line x1={cx} x2={cx} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={cx - bw / 2} y={top} width={bw} height={bodyH} fill={color} rx={1} />
    </g>
  );
}

/** Daily candles with our buys (▲) and sells (▼); volume in its own small chart underneath (no second axis). */
export function CandleChart({ candles, marks }: { candles: Candle[]; marks: { date: string; price: number; side: string }[] }) {
  if (candles.length < 2) return <Wait>No price history for this stock in the dataset.</Wait>;
  const data = candles.map((c) => ({ ...c, range: [c.low, c.high] as [number, number] }));
  return (
    <>
      <div className="h-72 w-full">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ left: 4, right: 12, top: 8, bottom: 0 }} barCategoryGap={1}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="date" {...axis} minTickGap={40} />
            <YAxis {...axis} width={64} domain={["auto", "auto"]} tickFormatter={(v: number) => compactRupees(v)} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)", opacity: 0.4 }}
              content={({ active, payload }) => {
                const c = active && payload?.[0]?.payload as Candle | undefined;
                if (!c) return null;
                return (
                  <div style={tooltipStyle} className="px-3 py-2 tabular-nums">
                    <div className="mb-1 font-medium">{c.date}</div>
                    <div>Open {rupees(c.open)} · Close {rupees(c.close)}</div>
                    <div>High {rupees(c.high)} · Low {rupees(c.low)}</div>
                  </div>
                );
              }} />
            <Bar dataKey="range" shape={(props: unknown) => <CandleShape {...(props as ShapeProps)} />} isAnimationActive={false} />
            {marks.map((m, i) => (
              <ReferenceDot key={i} x={m.date} y={m.price} r={6} ifOverflow="extendDomain"
                fill={m.side === "buy" ? "var(--up)" : "var(--down)"} stroke="var(--card)" strokeWidth={2}
                label={{ value: m.side === "buy" ? "▲" : "▼", position: m.side === "buy" ? "bottom" : "top", fontSize: 11, fill: "var(--foreground)" }} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 h-20 w-full">
        <ResponsiveContainer>
          <BarChart data={candles} margin={{ left: 4, right: 12, top: 0, bottom: 0 }} barCategoryGap={1}>
            <XAxis dataKey="date" hide />
            <YAxis {...axis} width={64} tickFormatter={(v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : `${(v / 1e3).toFixed(0)}K`)} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)", opacity: 0.4 }} formatter={(v) => [Number(v).toLocaleString("en-IN"), "Volume"]} />
            <Bar dataKey="volume" fill="var(--muted-foreground)" fillOpacity={0.5} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

/** Rank over time (1 = model's favorite), so up the chart = better. */
export function RankChart({ points }: { points: { date: string; rank: number; of: number }[] }) {
  if (points.length < 2) return <Wait h="h-40">Rank history builds up day by day.</Wait>;
  return (
    <div className="h-40 w-full">
      <ResponsiveContainer>
        <LineChart data={points} margin={{ left: 4, right: 12, top: 8, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="date" {...axis} minTickGap={32} />
          <YAxis {...axis} width={44} reversed domain={[1, "auto"]} allowDecimals={false} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v, _n, item) => [`#${v} of ${(item?.payload as { of: number })?.of ?? "?"}`, "Rank"]} />
          <Line type="monotone" dataKey="rank" stroke="var(--brand)" strokeWidth={2} dot={points.length < 30 ? { r: 3 } : false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal bars, largest first: feature importance and the like. */
export function HBars({ items, format, height = 28 }: { items: { name: string; value: number }[]; format?: (v: number) => string; height?: number }) {
  if (!items.length) return <Wait h="h-24">No data.</Wait>;
  return (
    <div className="w-full" style={{ height: items.length * height + 16 }}>
      <ResponsiveContainer>
        <BarChart data={items} layout="vertical" margin={{ left: 0, right: 40, top: 0, bottom: 0 }} barCategoryGap={4}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" {...axis} width={120} interval={0} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)", opacity: 0.4 }} formatter={(v) => [format ? format(Number(v)) : String(v), ""]} />
          <Bar dataKey="value" fill="var(--brand)" radius={[0, 3, 3, 0]}
            label={{ position: "right", fontSize: 11, fill: "var(--muted-foreground)", formatter: (v: unknown) => (format ? format(Number(v)) : String(v)) }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** One bar per day, blue above zero, red below (rank IC, daily P&L…). */
export function SignedBars({ points, format, name }: { points: { x: string; y: number; dim?: boolean }[]; format: (v: number) => string; name: string }) {
  if (!points.length) return <Wait h="h-48">Builds up as signal days pass.</Wait>;
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer>
        <BarChart data={points} margin={{ left: 4, right: 12, top: 8, bottom: 0 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="x" {...axis} minTickGap={32} />
          <YAxis {...axis} width={48} tickFormatter={format} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)", opacity: 0.4 }} formatter={(v, _n, item) => [format(Number(v)) + ((item?.payload as { dim?: boolean })?.dim ? " (window not complete)" : ""), name]} />
          <Bar dataKey="y" radius={[2, 2, 0, 0]}>
            {points.map((p, i) => <Cell key={i} fill={p.y >= 0 ? "var(--up)" : "var(--down)"} fillOpacity={p.dim ? 0.4 : 1} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Two series per day: our picks (brand) vs the average stock (muted gray). */
export function PicksVsMarket({ points }: { points: { x: string; picks: number; market: number }[] }) {
  if (!points.length) return <Wait h="h-48">Builds up as signal days pass.</Wait>;
  return (
    <>
      <div className="mb-3 flex gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-brand" />Top picks</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-muted-foreground/60" />Average stock</span>
      </div>
      <div className="h-48 w-full">
        <ResponsiveContainer>
          <BarChart data={points} margin={{ left: 4, right: 12, top: 8, bottom: 0 }} barGap={2} barCategoryGap={6}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="x" {...axis} minTickGap={32} />
            <YAxis {...axis} width={48} tickFormatter={(v: number) => pct(v, 0)} />
            <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)", opacity: 0.4 }} formatter={(v, n) => [pct(Number(v)), String(n)]} />
            <Bar name="Top picks" dataKey="picks" fill="var(--brand)" radius={[2, 2, 0, 0]} />
            <Bar name="Average stock" dataKey="market" fill="var(--muted-foreground)" fillOpacity={0.6} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

/** Headlines per day split by rough tone: blue positive, red negative, gray neutral (stacked). */
export function ToneBars({ days }: { days: { day: string; pos: number; neg: number; neutral: number }[] }) {
  if (!days.length) return <Wait h="h-40">No headlines yet.</Wait>;
  return (
    <>
      <div className="mb-3 flex gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-up" />Positive words</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-down" />Negative words</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-muted-foreground/40" />Neutral</span>
      </div>
      <div className="h-40 w-full">
        <ResponsiveContainer>
          <BarChart data={days} margin={{ left: 4, right: 12, top: 4, bottom: 0 }} barCategoryGap={2}>
            <XAxis dataKey="day" {...axis} minTickGap={32} />
            <YAxis {...axis} width={36} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--muted)", opacity: 0.4 }} />
            <Bar name="Positive" dataKey="pos" stackId="t" fill="var(--up)" />
            <Bar name="Negative" dataKey="neg" stackId="t" fill="var(--down)" />
            <Bar name="Neutral" dataKey="neutral" stackId="t" fill="var(--muted-foreground)" fillOpacity={0.4} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
