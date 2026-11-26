"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import { useApi, when } from "@/lib/api";
import { Badge, Card, ErrorNote, PageTitle, Stat, Table } from "@/components/ui";

type Status = {
  server_time: string;
  timers: { unit: string; next_us: number | null; last_us: number | null; result: string | null; active: string | null }[];
  news: { n: number; last: string } | null;
  breeze_calls: { day: string; n: number } | null;
  breeze_windows: { interval: string; status: string; n: number; rows: number | null }[];
};

const usTime = (us: number | null) => (us ? new Date(us / 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "–");

export default function SystemPage() {
  const { data, error } = useApi<Status>("/api/status", 30_000);
  return (
    <>
      <PageTitle sub="Jobs on the live server. Training, signals and data backfills run on GitHub Actions.">System</PageTitle>
      <ErrorNote error={error} />
      <div className="mb-8 flex flex-wrap gap-x-12 gap-y-6">
        <Stat label="Server time" value={when(data?.server_time)} />
        <Stat label="News items" value={data?.news ? data.news.n.toLocaleString("en-IN") : "–"} />
        <Stat label="Breeze calls today" value={data?.breeze_calls ? `${data.breeze_calls.n} / 5,000` : "–"} />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Scheduled jobs">
          <Table head={["Job", "Last run", "Next run", "Result"]} rows={(data?.timers ?? []).map((t) => [
            t.unit.replace("t2-", ""), usTime(t.last_us), usTime(t.next_us),
            t.result === "success" ? <Badge key="r" kind="ok"><CheckCircle2 className="size-3.5" />ok</Badge>
              : t.result ? <Badge key="r" kind="danger"><XCircle className="size-3.5" />{t.result}</Badge> : "–",
          ])} />
        </Card>
        <Card title="Breeze intraday backfill">
          <Table head={["Interval", "Status", "Windows", "Candles"]} rows={(data?.breeze_windows ?? []).map((w) => [
            w.interval, w.status, w.n.toLocaleString("en-IN"), (w.rows ?? 0).toLocaleString("en-IN")])} empty="Not started yet." />
        </Card>
      </div>
    </>
  );
}
