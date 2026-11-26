"use client";

import { useState } from "react";
import { Power } from "lucide-react";
import type { Kill } from "@/lib/api";
import { when } from "@/lib/api";
import { Badge, Button, Input } from "@/components/ui";

/** Stops all new positions (exits still go through). Signed-in users only. */
export function KillSwitch({ kill, onChange }: { kill: Kill | undefined; onChange: () => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function set(on: boolean) {
    setBusy(true);
    setMsg(null);
    const r = await fetch("/api/kill", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ on, reason }),
    });
    setBusy(false);
    if (r.status === 401) window.location.href = "/login";
    else if (!r.ok) setMsg(`Failed: ${r.status}`);
    onChange();
  }

  const on = kill?.on;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {on ? <Badge kind="danger">Kill switch ON</Badge> : <Badge kind="ok">Trading allowed</Badge>}
        {on && <span className="text-sm text-muted-foreground">since {when(kill?.since)} · {kill?.reason}</span>}
      </div>
      <div className="flex flex-wrap gap-3">
        {!on && <Input placeholder="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />}
        {on ? (
          <Button variant="outline" onClick={() => set(false)} disabled={busy}>Release</Button>
        ) : (
          <Button variant="danger" onClick={() => set(true)} disabled={busy}><Power className="size-4" />Stop new positions</Button>
        )}
      </div>
      {msg && <p className="text-sm text-destructive">{msg}</p>}
    </div>
  );
}
