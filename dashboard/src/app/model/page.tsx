"use client";

import { useApi } from "@/lib/api";
import { Card, ErrorNote, PageTitle, Stat, Table } from "@/components/ui";

type Meta = {
  trained_on: string; data_last_date: string; train_rows: number; code_commit: string; data_commit: string;
  features: string[]; book: { k: number; exit_k: number; notional_per_position: number };
  recipe: { target: string; train_years: number; rounds: number; universe: string; extras: string[] };
};

export default function ModelPage() {
  const { data, error } = useApi<Meta>("/api/model", 600_000);
  return (
    <>
      <PageTitle sub="The model the paper book trades. Retrained every Sunday on Actions; every version is kept on Hugging Face.">
        Model
      </PageTitle>
      <ErrorNote error={error} />
      <div className="mb-8 flex flex-wrap gap-x-12 gap-y-6">
        <Stat label="Trained on" value={data?.trained_on ?? "–"} />
        <Stat label="Data up to" value={data?.data_last_date ?? "–"} />
        <Stat label="Training rows" value={data ? data.train_rows.toLocaleString("en-IN") : "–"} />
        <Stat label="Target" value={data ? `${data.recipe.target === "y5" ? "5-day" : "next-day"} rank` : "–"} />
        <Stat label="Book" value={data ? `${data.book.k}+${data.book.k}, buffer ${data.book.exit_k}` : "–"} />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Recipe">
          <Table head={["Setting", "Value"]} rows={data ? [
            ["Universe", data.recipe.universe], ["Feature groups", ["eod", ...data.recipe.extras].join(", ")],
            ["Training window", `${data.recipe.train_years} years`], ["Boosting rounds", data.recipe.rounds],
            ["Code commit", <code key="c" className="font-mono text-xs">{data.code_commit.slice(0, 10)}</code>],
            ["Data commit", <code key="d" className="font-mono text-xs">{data.data_commit.slice(0, 10)}</code>],
          ] : []} />
        </Card>
        <Card title={`Features (${data?.features.length ?? 0})`}>
          <p className="text-sm leading-7 text-muted-foreground">{data?.features.join(" · ")}</p>
        </Card>
      </div>
    </>
  );
}
