"use client";

import { useState } from "react";
import { BookOpen, ExternalLink, FileText, Search } from "lucide-react";
import { useApi, when } from "@/lib/api";
import { Badge, Button, ErrorNote, Input, PageTitle } from "@/components/ui";
import { cn } from "@/lib/cn";

type Item = {
  id: string; source: string; category: string; url: string; title: string | null; summary: string | null;
  published_at: string | null; first_seen_at: string; tickers: string | null; has_text: number;
  link: string; raw_url: string | null; raw_type: string | null;
};

const GROUPS = [
  { key: "articles", label: "Articles" },
  { key: "filings", label: "Exchange filings" },
  { key: "regulators", label: "Regulators" },
  { key: "all", label: "All" },
];

const SOURCE: Record<string, string> = {
  news: "Press", aggregator: "Google News", exchange: "NSE filing", regulator: "Regulator",
};

/** Feed summaries are untrusted HTML: parse them in an inert document (no scripts, no event handlers, no
 *  image loads) and keep only the text. Never assign them to innerHTML of the live page. */
function stripHtml(s: string | null): string {
  if (!s) return "";
  const doc = new DOMParser().parseFromString(s, "text/html");
  return (doc.body.textContent ?? "").trim();
}

function Reader({ id }: { id: string }) {
  const { data, error } = useApi<{ text: string }>(`/api/news/${id}`, 0);
  if (error) return <p className="mt-3 text-sm text-down">Could not load the text.</p>;
  if (!data) return <p className="mt-3 text-sm text-muted-foreground">Loading…</p>;
  return (
    <div className="mt-3 max-h-96 overflow-y-auto whitespace-pre-line rounded-lg bg-muted/60 px-4 py-3 text-sm leading-6">
      {data.text || "No text was extracted for this article."}
    </div>
  );
}

export default function NewsPage() {
  const [q, setQ] = useState("");
  const [symbol, setSymbol] = useState("");
  const [group, setGroup] = useState("articles");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const { data, error } = useApi<{ items: Item[] }>(`/api/news?limit=100&group=${group}${query}`, 120_000);

  return (
    <>
      <PageTitle sub="Collected every 5 minutes: financial press, NSE filings and regulators, tagged with NSE symbols.">
        News
      </PageTitle>
      <div className="mb-4 flex flex-wrap gap-2">
        {GROUPS.map((g) => (
          <button key={g.key} type="button" onClick={() => { setGroup(g.key); setOpen(null); }}
            className={cn("h-11 rounded-md px-5 text-sm font-medium transition-colors",
              group === g.key ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
            {g.label}
          </button>
        ))}
      </div>
      <form className="mb-8 flex flex-wrap gap-3" onSubmit={(e) => {
        e.preventDefault();
        setQuery(`${q ? `&q=${encodeURIComponent(q)}` : ""}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ""}`);
      }}>
        <Input placeholder="Search headlines" value={q} onChange={(e) => setQ(e.target.value)} />
        <Input placeholder="Symbol, e.g. TCS" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-44" />
        <Button type="submit"><Search className="size-4" />Search</Button>
      </form>
      <ErrorNote error={error} />
      {data && !data.items.length && <p className="text-sm text-muted-foreground">Nothing matches.</p>}
      <ul className="space-y-1">
        {(data?.items ?? []).map((n) => {
          const summary = stripHtml(n.summary);
          return (
            <li key={n.id} className="rounded-lg px-3 py-3 hover:bg-muted/40">
              <a href={n.link} target="_blank" rel="noreferrer noopener" className="group inline-flex items-start gap-2 font-medium">
                <span className="group-hover:underline">{n.title ?? n.url}</span>
                <ExternalLink className="mt-1 size-3.5 shrink-0 text-muted-foreground" />
              </a>
              {summary && summary !== n.title && (
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{summary}</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge kind={n.category === "exchange" ? "brand" : "muted"}>{SOURCE[n.category] ?? n.category}</Badge>
                <span>{n.source.replace(/_/g, " ")}</span><span>·</span><span>{when(n.published_at ?? n.first_seen_at)}</span>
                {(n.tickers ?? "").split(",").filter(Boolean).slice(0, 6).map((t) => (
                  <button key={t} type="button" onClick={() => { setSymbol(t); setQuery(`&symbol=${t}`); }}
                    className="rounded-md bg-up/15 px-2.5 py-1 font-medium text-up hover:bg-up/25">{t}</button>
                ))}
                {n.has_text ? (
                  <button type="button" onClick={() => setOpen(open === n.id ? null : n.id)}
                    className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 font-medium text-foreground hover:bg-muted">
                    <BookOpen className="size-3.5" />{open === n.id ? "Hide" : "Read"}
                  </button>
                ) : null}
                {n.raw_url && (
                  <a href={n.raw_url} target="_blank" rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 hover:bg-muted">
                    <FileText className="size-3.5" />raw {n.raw_type?.toUpperCase()}
                  </a>
                )}
              </div>
              {open === n.id && <Reader id={n.id} />}
            </li>
          );
        })}
      </ul>
    </>
  );
}
