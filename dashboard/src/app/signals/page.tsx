"use client";

import { num, rupees, useApi } from "@/lib/api";
import { Card, ErrorNote, PageTitle, Table } from "@/components/ui";

type Row = { rank: number; symbol: string; score: number; close: number; lot_size: number | null; fut_expiry: string | null };

export default function SignalsPage() {
  const { data, error } = useApi<{ date: string | null; rows: Row[] }>("/api/signals", 300_000);
  const rows = data?.rows ?? [];
  const table = (rs: Row[]) => rs.map((r) => [r.rank, <span key="s" className="font-medium">{r.symbol}</span>,
    num(r.score, 4), rupees(r.close), r.lot_size ?? "–", r.fut_expiry ?? "–"]);
  return (
    <>
      <PageTitle sub={`The champion's ranking of every F&O stock for the next 5 sessions${data?.date ? `, from the ${data.date} close` : ""}.`}>
        Signals
      </PageTitle>
      <ErrorNote error={error} />
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Strongest (long side)"><Table head={["Rank", "Symbol", "Score", "Close", "Lot", "Expiry"]} rows={table(rows.slice(0, 25))} /></Card>
        <Card title="Weakest (short side)"><Table head={["Rank", "Symbol", "Score", "Close", "Lot", "Expiry"]} rows={table(rows.slice(-25).reverse())} /></Card>
      </div>
    </>
  );
}
