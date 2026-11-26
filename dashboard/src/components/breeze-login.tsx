"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, LogIn } from "lucide-react";
import { useApi, when } from "@/lib/api";
import { Badge, Button } from "@/components/ui";

type Status = { has_session: boolean; saved_at: string | null; valid_today: boolean };

/** Daily Breeze login: ICICI's own page, then back to /breeze/callback which saves the session. */
export function BreezeLogin() {
  const { data } = useApi<Status>("/api/breeze/status", 60_000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setErr(null);
    const r = await fetch("/api/breeze/login-url");
    if (!r.ok) {
      setBusy(false);
      setErr(`Could not start the login (${r.status})`);
      return;
    }
    window.location.href = (await r.json()).url;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {data?.valid_today
          ? <Badge kind="ok"><CheckCircle2 className="size-3.5" />Connected today</Badge>
          : <Badge kind="warn"><AlertTriangle className="size-3.5" />Login needed today</Badge>}
        {data?.saved_at && <span className="text-sm text-muted-foreground">last login {when(data.saved_at)}</span>}
      </div>
      <p className="text-sm text-muted-foreground">
        Needed once per trading day before 09:20 IST for paper trading and data collection.
      </p>
      <Button onClick={go} disabled={busy} variant={data?.valid_today ? "outline" : "primary"}>
        <LogIn className="size-4" />Log in to Breeze
      </Button>
      {err && <p className="text-sm text-destructive">{err}</p>}
    </div>
  );
}
