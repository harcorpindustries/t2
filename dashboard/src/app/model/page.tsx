"use client";

import { type Quality, pct, useApi } from "@/lib/api";
import { Badge, Card, ErrorNote, Loading, PageTitle, Stat, Table } from "@/components/ui";
import { HBars, SignedBars } from "@/components/charts";

type Meta = {
  trained_on: string; data_last_date: string; train_rows: number; code_commit: string; data_commit: string;
  features: string[]; book: { k: number; exit_k: number; notional_per_position: number; vehicle?: string; long_only?: boolean };
  recipe: { target: string; train_years: number; rounds: number; universe: string; extras: string[] };
  importance: { feature: string; splits: number }[];
  history: { trained_on: string; data_last_date: string; train_rows: number; code_commit: string; data_commit: string }[];
  challengers?: Challenger[];
};

type Scores = { ic: number; ic_hit: number; long_hit: number; annual: number; sharpe: number; max_dd: number };
type Challenger = { name: string; finished: string; years: number[]; verdict: string; params: number; neural: Scores; lightgbm: Scores;
  agreement?: number | null; blends?: { label: string; scores: Scores }[] };

/** Plain names for the model's inputs (the rest keep their code names). */
const LABEL: Record<string, string> = {
  lr: "1-day return", r5: "5-day return", r20: "20-day return", r60: "60-day return", r120: "120-day return",
  vol20: "20-day volatility", vol60: "60-day volatility", hl: "day's range", hl20: "20-day avg range", gap: "opening gap",
  oc: "open→close move", dd60: "60-day drawdown", lturn: "turnover (log)", turn_ratio: "turnover surge",
  deliv_pct: "delivery %", deliv_z: "delivery surge", mkt_r1: "market 1-day", mkt_r5: "market 5-day",
  mkt_r20: "market 20-day", mkt_vol20: "market volatility", breadth: "market breadth", dow: "weekday",
  fut_oi_chg1: "futures OI 1-day", fut_oi_chg5: "futures OI 5-day", basis_ann: "futures basis", fo_turn_ratio: "F&O activity",
  pcr: "put/call ratio", pcr_chg5: "put/call change", news_n1: "news count 1-day", news_n5: "news count 5-day",
  news_tone1: "news tone 1-day", news_tone5: "news tone 5-day", news_z: "news surge",
};
const label = (f: string) => {
  const base = f.endsWith("_rk") ? f.slice(0, -3) : f;
  return (LABEL[base] ?? base) + (f.endsWith("_rk") ? " (rank)" : "");
};

export default function ModelPage() {
  const { data, error, reload } = useApi<Meta>("/api/model", 600_000);
  const { data: q } = useApi<Quality>("/api/signals/quality", 1_800_000);
  const total = (data?.importance ?? []).reduce((a, b) => a + b.splits, 0) || 1;
  const age = data ? Math.floor((Date.now() - new Date(`${data.trained_on}T00:00:00Z`).getTime()) / 86_400_000) : null;
  const ics = (q?.days ?? []).filter((d) => d.complete).map((d) => d.ic);
  const rolling = ics.length >= 5 ? ics.slice(-20).reduce((a, b) => a + b, 0) / Math.min(20, ics.length) : null;
  return (
    <>
      <PageTitle sub="The model the paper book trades. Retrained every Sunday on GitHub Actions; every version is kept on Hugging Face.">
        Model
      </PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      {!data && !error ? <Loading rows={6} /> : data && (
        <div className="grid gap-5">
          <div className="flex flex-wrap gap-x-10 gap-y-5">
            <Stat label="Trained on" value={data.trained_on} sub={age != null ? `${age} days ago` : undefined} />
            <Stat label="Data up to" value={data.data_last_date} />
            <Stat label="Training rows" value={data.train_rows.toLocaleString("en-IN")} />
            <Stat label="Predicts" value={`${data.recipe.target === "y5" ? "5-day" : "next-day"} rank`} />
            <Stat label="Book" value={data.book.long_only ? `top ${data.book.k}` : `${data.book.k} + ${data.book.k}`} sub={`exit below #${data.book.exit_k}`} />
            <Stat label="Live rank IC (last 20)" value={rolling != null ? rolling.toFixed(3) : "–"} tone={rolling != null ? (rolling > 0 ? "pos" : "neg") : undefined}
              sub={rolling == null ? "needs 5 scored signal days" : rolling > 0 ? "still ranks better than chance" : "watch: no skill lately"} />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="What the model leans on" action={<span className="text-xs text-muted-foreground">share of tree splits, top 20</span>}>
              <HBars items={(data.importance ?? []).slice(0, 20).map((i) => ({ name: label(i.feature), value: i.splits / total }))}
                format={(v) => `${(v * 100).toFixed(1)}%`} height={24} />
            </Card>
            <div className="grid content-start gap-5">
              <Card title="Live skill: rank IC per signal day">
                <SignedBars name="Rank IC" format={(v) => v.toFixed(2)} points={(q?.days ?? []).map((d) => ({ x: d.date, y: d.ic, dim: !d.complete }))} />
                <p className="mt-2 text-xs text-muted-foreground">How well each day&apos;s ranking matched what stocks did over the next 5 sessions (Spearman). Persistent values near or below 0 mean the model has decayed.</p>
              </Card>
              <Card title="Recipe">
                <Table head={["Setting", "Value"]} rows={[
                  ["Universe", data.recipe.universe === "all" ? "all liquid NSE stocks" : "F&O stocks"],
                  ["Feature groups", ["price & volume", ...data.recipe.extras.map((e) => (e === "fno" ? "F&O positioning" : e === "news" ? "news flow" : e))].join(", ")],
                  ["Training window", `${data.recipe.train_years} years`],
                  ["Boosting rounds", data.recipe.rounds],
                  ["Inputs", data.features.length],
                  ["Code commit", <code key="c" className="font-mono text-xs">{data.code_commit.slice(0, 10)}</code>],
                  ["Data commit", <code key="d" className="font-mono text-xs">{data.data_commit.slice(0, 10)}</code>],
                ]} />
              </Card>
            </div>
          </div>

          <Card title="Challengers" action={<span className="text-xs text-muted-foreground">same years, same tests, same cash book</span>}>
            {!(data.challengers ?? []).length ? (
              <p className="py-6 text-sm text-muted-foreground">The first neural challenger is training on GitHub Actions. Its comparison appears here when it finishes.</p>
            ) : (data.challengers ?? []).map((c) => (
              <div key={c.finished + c.verdict} className="mb-6 last:mb-0">
                <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
                  <span className="font-medium">{c.name}</span>
                  <span className="text-muted-foreground">{c.params.toLocaleString("en-IN")} parameters · tested {c.years[0]}–{c.years[c.years.length - 1]} · {c.finished}</span>
                  <Badge kind={c.verdict.includes("beats") ? "ok" : "muted"}>{c.verdict}</Badge>
                  {c.agreement != null && <span className="text-xs text-muted-foreground">picks agree {c.agreement.toFixed(2)}</span>}
                </div>
                <Table head={["Model", "Rank IC", "IC > 0 days", "Top-10 up days", "Cash book / year", "Sharpe", "Max drawdown"]}
                  rows={([["Neural", c.neural], ["LightGBM champion", c.lightgbm], ...(c.blends ?? []).map((b) => [b.label, b.scores])] as [string, Scores][]).map(([n, r]) => [
                    n, r.ic.toFixed(4), pct(r.ic_hit, 0, false), pct(r.long_hit, 0, false), pct(r.annual, 1), r.sharpe.toFixed(2), pct(r.max_dd, 1)])} />
              </div>
            ))}
          </Card>

          <Card title="Training history">
            <Table head={["Trained on", "Data up to", "Rows", "Code", "Data"]}
              rows={[...(data.history ?? [])].reverse().map((h) => [h.trained_on, h.data_last_date, h.train_rows?.toLocaleString("en-IN") ?? "–",
                <code key="c" className="font-mono text-xs">{h.code_commit?.slice(0, 8)}</code>, <code key="d" className="font-mono text-xs">{h.data_commit?.slice(0, 8)}</code>])}
              empty="History starts with the next weekly retrain." />
          </Card>
        </div>
      )}
    </>
  );
}
