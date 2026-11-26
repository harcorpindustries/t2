"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { rupees } from "@/lib/api";

export function EquityChart({ points }: { points: { day: string; equity: number }[] }) {
  if (points.length < 2) {
    return <p className="py-10 text-sm text-muted-foreground">The curve appears after two marked trading days.</p>;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <AreaChart data={points} margin={{ left: 8, right: 8, top: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--brand)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--brand)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={12} stroke="var(--muted-foreground)" minTickGap={32} />
          <YAxis tickLine={false} axisLine={false} fontSize={12} stroke="var(--muted-foreground)" width={90}
            domain={["auto", "auto"]} tickFormatter={(v: number) => rupees(v)} />
          <Tooltip formatter={(v) => rupees(Number(v))} contentStyle={{ borderRadius: 8, border: "none",
            boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)", background: "var(--card)", color: "var(--foreground)" }} />
          <Area type="monotone" dataKey="equity" stroke="var(--brand)" strokeWidth={2} fill="url(#eq)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
