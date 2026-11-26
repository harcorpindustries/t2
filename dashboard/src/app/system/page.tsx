"use client";

import { useState } from "react";
import { CheckCircle2, FileText, XCircle } from "lucide-react";
import { bytes, useApi, when } from "@/lib/api";
import { istNow } from "@/lib/market";
import { Badge, Card, ErrorNote, Loading, Meter, PageTitle, Stat, Table } from "@/components/ui";

type Status = {
  server_time: string;
  timers: { unit: string; next_us: number | null; last_us: number | null; result: string | null; active: string | null }[];
  news: { n: number; last: string } | null;
  breeze_calls: { day: string; n: number } | null;
  breeze_windows: { interval: string; status: string; n: number; rows: number | null }[];
  server: { load: number[]; cpus: number | null; mem_total: number | null; mem_used: number | null; disk_total: number; disk_used: number };
  freshness: { name: string; last: string; rows: number }[];
  hf_gb: number | null;
  hf_free_gb: number;
  breeze_budget: number;
  alerts: boolean;
};

const usTime = (us: number | null) => (us ? new Date(us / 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "–");

const ageDays = (iso: string) => Math.floor((Date.now() - new Date(iso.length <= 10 ? `${iso}T00:00:00Z` : iso).getTime()) / 86_400_000);

function Logs({ unit }: { unit: string }) {
  const { data, error } = useApi<{ text: string }>(`/api/logs/${unit}`, 0);
  if (error) return <p className="text-sm text-down">Could not read the log: {error}</p>;
  if (!data) return <Loading rows={4} />;
  return (
    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/60 p-3 font-mono text-xs leading-5">
      {data.text.trim() || "No log lines yet."}
    </pre>
  );
}

export default function SystemPage() {
  const { data, error, reload } = useApi<Status>("/api/status", 30_000);
  const [logs, setLogs] = useState<string | null>(null);
  const s = data?.server;
  const today = data?.breeze_calls && data.breeze_calls.day === istNow().toISOString().slice(0, 10) ? data.breeze_calls.n : 0;
  return (
    <>
      <PageTitle sub="Jobs on the live server and the health of every data feed. Training, signals and data backfills run on GitHub Actions.">
        System
      </PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      {!data && !error ? <Loading rows={8} /> : data && (
        <div className="grid gap-5">
          <div className="flex flex-wrap gap-x-10 gap-y-5">
            <Stat label="Server time" value={when(data.server_time)} />
            <Stat label="CPU load (1 min)" value={s ? s.load[0].toFixed(2) : "–"} sub={s?.cpus ? `${s.cpus} cores` : undefined} />
            <Stat label="News items" value={data.news ? data.news.n.toLocaleString("en-IN") : "–"} sub={data.news ? `last ${when(data.news.last)}` : undefined} />
            <Stat label="Phone alerts" value={data.alerts ? "On" : "Off"} sub={data.alerts ? "Telegram" : "set up in Settings"} />
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <Card title="Budgets">
              <div className="space-y-5">
                <Meter label="Breeze API calls today" value={today} limit={data.breeze_budget} format={(v) => v.toLocaleString("en-IN")} />
                <Meter label="Hugging Face storage (private, free tier)" value={data.hf_gb ?? 0} limit={data.hf_free_gb} format={(v) => `${v.toFixed(1)} GB`} />
                {s?.mem_total != null && s.mem_used != null && <Meter label="Server memory" value={s.mem_used} limit={s.mem_total} format={bytes} />}
                {s && <Meter label="Server disk" value={s.disk_used} limit={s.disk_total} format={bytes} />}
              </div>
            </Card>
            <Card title="Data freshness">
              <Table head={["Feed", "Latest", "Rows", ""]} rows={data.freshness.map((f) => {
                const age = ageDays(f.last);
                const ok = age <= (f.name === "News" ? 1 : 4);
                return [f.name, f.last.length > 10 ? when(f.last) : f.last, f.rows?.toLocaleString("en-IN") ?? "–",
                  ok ? <Badge key="b" kind="ok"><CheckCircle2 className="size-3.5" />fresh</Badge>
                    : <Badge key="b" kind="warn">{age} days old</Badge>];
              })} empty="No feed has reported yet." />
            </Card>
          </div>
          <Card title="Scheduled jobs">
            <Table head={["Job", "Last run", "Next run", "Result", ""]} rows={data.timers.map((t) => [
              t.unit.replace("t2-", ""), usTime(t.last_us), usTime(t.next_us),
              t.result === "success" ? <Badge key="r" kind="ok"><CheckCircle2 className="size-3.5" />ok</Badge>
                : t.result ? <Badge key="r" kind="danger"><XCircle className="size-3.5" />{t.result}</Badge> : "–",
              <button key="l" type="button" onClick={() => setLogs(logs === t.unit ? null : t.unit)}
                className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
                <FileText className="size-3.5" />{logs === t.unit ? "Hide log" : "Log"}
              </button>,
            ])} />
            {logs && <div className="mt-4"><div className="mb-2 text-sm font-medium">{logs}</div><Logs unit={logs} /></div>}
          </Card>
          <Card title="Breeze intraday backfill">
            <Table head={["Interval", "Status", "Windows", "Candles"]} rows={data.breeze_windows.map((w) => [
              w.interval, w.status, w.n.toLocaleString("en-IN"), (w.rows ?? 0).toLocaleString("en-IN")])} empty="Not started yet." />
          </Card>
        </div>
      )}
    </>
  );
}
