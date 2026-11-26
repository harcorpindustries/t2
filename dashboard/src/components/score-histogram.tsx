"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

/** How the model's scores spread across all ranked stocks; blue bins above zero, red below. */
export function ScoreHistogram({ scores }: { scores: number[] }) {
  if (scores.length < 10) return null;
  const lo = Math.min(...scores);
  const hi = Math.max(...scores);
  const n = 24;
  const width = (hi - lo) / n || 1;
  const bins = Array.from({ length: n }, (_, i) => ({ from: lo + i * width, to: lo + (i + 1) * width, count: 0 }));
  for (const s of scores) bins[Math.min(n - 1, Math.floor((s - lo) / width))].count += 1;
  const data = bins.map((b) => ({ ...b, mid: (b.from + b.to) / 2, label: `${b.from.toFixed(3)} to ${b.to.toFixed(3)}` }));
  return (
    <div className="h-48 w-full">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ left: 0, right: 8, top: 8, bottom: 0 }} barCategoryGap={2}>
          <XAxis dataKey="mid" tickLine={false} axisLine={false} fontSize={12} stroke="var(--muted-foreground)"
            tickFormatter={(v: number) => v.toFixed(2)} minTickGap={24} />
          <YAxis tickLine={false} axisLine={false} fontSize={12} stroke="var(--muted-foreground)" width={36} allowDecimals={false} />
          <Tooltip cursor={{ fill: "var(--muted)" }}
            formatter={(v) => [`${v} stocks`, "count"]} labelFormatter={(_, p) => (p?.[0]?.payload?.label as string) ?? ""}
            contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
              background: "var(--card)", color: "var(--foreground)" }} />
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {data.map((d, i) => <Cell key={i} fill={d.mid >= 0 ? "var(--up)" : "var(--down)"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
