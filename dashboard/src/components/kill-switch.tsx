"use client";

import { useState } from "react";
import { CheckCircle2, OctagonX, Power } from "lucide-react";
import type { Kill } from "@/lib/api";
import { when } from "@/lib/api";
import { Badge, Button, Input } from "@/components/ui";
import { Confirm } from "@/components/confirm";
import { useToast } from "@/components/toast";

/** Stops all new positions (exits still go through). Signed-in users only. */
export function KillSwitch({ kill, onChange }: { kill: Kill | undefined; onChange: () => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [asking, setAsking] = useState<"on" | "off" | null>(null);
  const toast = useToast();

  async function set(on: boolean) {
    setAsking(null);
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
    else toast(on ? "Kill switch on: no new positions" : "Kill switch released");
    onChange();
  }

  const on = kill?.on;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {on
          ? <Badge kind="danger"><OctagonX className="size-3.5" />Kill switch ON</Badge>
          : <Badge kind="ok"><CheckCircle2 className="size-3.5" />Trading allowed</Badge>}
        {on && <span className="text-sm text-muted-foreground">since {when(kill?.since)} · {kill?.reason}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {!on && <Input placeholder="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} className="flex-1 basis-40" />}
        {on ? (
          <Button variant="outline" onClick={() => setAsking("off")} disabled={busy}>Release</Button>
        ) : (
          <Button variant="danger" onClick={() => setAsking("on")} disabled={busy}><Power className="size-4" />Stop new positions</Button>
        )}
      </div>
      <Confirm open={asking === "on"} title="Stop all new positions?" confirmLabel="Stop new positions" danger busy={busy}
        onConfirm={() => set(true)} onCancel={() => setAsking(null)}>
        The trader will not open any new position until you release the switch. Exits and square-offs still go
        through, and nothing already held is sold because of this.
      </Confirm>
      <Confirm open={asking === "off"} title="Release the kill switch?" confirmLabel="Release" busy={busy}
        onConfirm={() => set(false)} onCancel={() => setAsking(null)}>
        New positions are allowed again: the next session (09:20 IST on a trading day) will trade normally.
      </Confirm>
      {msg && <p className="text-sm text-destructive">{msg}</p>}
    </div>
  );
}
