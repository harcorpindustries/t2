"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { useApi, when } from "@/lib/api";
import { Badge, Button, ErrorNote, Input, PageTitle } from "@/components/ui";

type Item = { source: string; category: string; url: string; title: string | null; summary: string | null;
  published_at: string | null; first_seen_at: string; tickers: string | null };

export default function NewsPage() {
  const [q, setQ] = useState("");
  const [symbol, setSymbol] = useState("");
  const [query, setQuery] = useState("");
  const { data, error } = useApi<{ items: Item[] }>(`/api/news?limit=100${query}`, 120_000);
  return (
    <>
      <PageTitle sub="Everything the crawler has collected: exchange filings, regulators and financial press, tagged with NSE symbols.">
        News
      </PageTitle>
      <form className="mb-8 flex flex-wrap gap-3" onSubmit={(e) => {
        e.preventDefault();
        setQuery(`${q ? `&q=${encodeURIComponent(q)}` : ""}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ""}`);
      }}>
        <Input placeholder="Search headlines" value={q} onChange={(e) => setQ(e.target.value)} />
        <Input placeholder="Symbol, e.g. TCS" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-44" />
        <Button type="submit"><Search className="size-4" />Search</Button>
      </form>
      <ErrorNote error={error} />
      <ul className="space-y-1">
        {(data?.items ?? []).map((n) => (
          <li key={n.url} className="rounded-lg px-3 py-3 hover:bg-muted/60">
            <a href={n.url} target="_blank" rel="noreferrer noopener" className="font-medium hover:underline">{n.title ?? n.url}</a>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>{n.source}</span><span>·</span><span>{when(n.published_at ?? n.first_seen_at)}</span>
              {(n.tickers ?? "").split(",").filter(Boolean).slice(0, 6).map((t) => <Badge key={t}>{t}</Badge>)}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
