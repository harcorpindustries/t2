"use client";

import { useState } from "react";
import { BellRing, CheckCircle2, LogOut, XCircle } from "lucide-react";
import { compactRupees, post, rupees, useApi } from "@/lib/api";
import { Badge, Button, Card, ErrorNote, Loading, PageTitle, Table } from "@/components/ui";
import { Confirm } from "@/components/confirm";
import { useToast } from "@/components/toast";
import { ThemeToggle } from "@/components/theme";
import { PasswordForm, SecretsPanel } from "@/components/secrets";

type Settings = {
  book: { capital?: number; k?: number; exit_k?: number; notional_per_position?: number; slippage_bps?: number;
    vehicle?: string; long_only?: boolean; signals?: string; risk?: Record<string, unknown> };
  alerts: boolean;
  session_days: number;
};

const SHORTCUTS: [string, string][] = [
  ["⌘K or /", "Search stocks, pages and actions"], ["⌘B", "Collapse or expand the sidebar"],
  ["g o", "Overview"], ["g b", "Book"], ["g s", "Signals"], ["g m", "Model"], ["g r", "Risk"], ["g n", "News"],
  ["g y", "System"], ["g ,", "Settings"],
];

export default function SettingsPage() {
  const { data, error, reload } = useApi<Settings>("/api/settings", 0);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const b = data?.book ?? {};

  async function revoke() {
    setAsking(false);
    setBusy(true);
    try {
      await post("/api/sessions/revoke");
      toast("Every other browser is signed out");
    } catch (e) {
      toast(`Failed: ${e instanceof Error ? e.message : e}`, "error");
    }
    setBusy(false);
  }

  async function testAlert() {
    try {
      const r = await post<{ sent: boolean }>("/api/alerts/test");
      toast(r.sent ? "Test alert sent" : "Not sent: alerts are not set up yet", r.sent ? "ok" : "error");
    } catch (e) {
      toast(`Failed: ${e instanceof Error ? e.message : e}`, "error");
    }
  }

  return (
    <>
      <PageTitle sub="How the paper book is set up, phone alerts, API keys and secrets, password, sessions and shortcuts.">Settings</PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      {!data && !error ? <Loading rows={6} /> : (
        <div className="grid gap-5 xl:grid-cols-2">
          <Card title="Paper book" action={<Badge>read-only</Badge>}>
            <Table head={["Setting", "Value"]} rows={[
              ["Starting capital", rupees(b.capital)],
              ["Instrument", b.vehicle === "delivery" ? "cash shares (delivery)" : "stock futures"],
              ["Direction", b.long_only ? "long only" : "long and short"],
              ["Positions", b.k != null ? (b.long_only ? `top ${b.k}` : `${b.k} long + ${b.k} short`) : "–"],
              ["Per position", compactRupees(b.notional_per_position)],
              ["Exit when rank falls below", b.exit_k != null ? `#${b.exit_k}` : "–"],
              ["Slippage assumed", b.slippage_bps != null ? `${b.slippage_bps} bps per fill` : "–"],
              ["Signals followed", b.signals ?? "–"],
            ]} />
            <p className="mt-4 text-xs text-muted-foreground">These live in config/paper/book.json. They change through a reviewed pull request, never from the browser.</p>
          </Card>
          <Card title="Risk limits" action={<Badge>read-only</Badge>}>
            <Table head={["Limit", "Value"]} rows={Object.entries(b.risk ?? {}).map(([k, v]) => [k.replace(/_/g, " "),
              Array.isArray(v) ? v.join(", ") : typeof v === "number" && v >= 1000 ? rupees(v) : String(v)])} />
          </Card>
          <Card title="Phone alerts">
            <div className="space-y-4">
              {data?.alerts
                ? <Badge kind="ok"><CheckCircle2 className="size-3.5" />Telegram alerts on</Badge>
                : <Badge kind="warn"><XCircle className="size-3.5" />Not set up</Badge>}
              <p className="text-sm text-muted-foreground">Breeze login reminder (08:45 and 09:10 on weekdays if not logged in), the open run&apos;s fills, the close summary, job failures and kill switch changes.</p>
              {!data?.alerts && <p className="text-sm text-muted-foreground">Add the Telegram bot token and chat ID under API keys and secrets below.</p>}
              <Button variant="outline" onClick={testAlert}><BellRing className="size-4" />Send a test alert</Button>
            </div>
          </Card>
          <Card title="Sessions and appearance">
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">A sign-in lasts {data?.session_days ?? 7} days on each browser. Signing out everywhere keeps only this browser signed in.</p>
              <Button variant="danger" onClick={() => setAsking(true)} disabled={busy}><LogOut className="size-4" />Sign out everywhere else</Button>
              <div className="max-w-xs pt-2"><ThemeToggle /></div>
            </div>
          </Card>
          <Card title="API keys and secrets" className="xl:col-span-2"><SecretsPanel /></Card>
          <Card title="Dashboard password" className="xl:col-span-2">
            <p className="mb-4 text-sm text-muted-foreground">Other signed-in browsers stay signed in; use &quot;Sign out everywhere else&quot; afterwards if you want them out.</p>
            <PasswordForm />
          </Card>
          <Card title="Keyboard shortcuts" className="xl:col-span-2">
            <div className="grid gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
              {SHORTCUTS.map(([k, d]) => (
                <div key={k} className="flex items-center gap-3 text-sm">
                  <kbd className="min-w-16 rounded bg-muted px-2 py-1 text-center font-mono text-xs">{k}</kbd>
                  <span className="text-muted-foreground">{d}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
      <Confirm open={asking} title="Sign out every other browser?" confirmLabel="Sign out others" danger busy={busy}
        onConfirm={revoke} onCancel={() => setAsking(false)}>
        Phones and computers signed in to T2 will need the password again. This browser stays signed in.
      </Confirm>
    </>
  );
}
