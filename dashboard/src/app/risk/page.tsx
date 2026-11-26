"use client";

import { useState } from "react";
import { CheckCircle2, LogOut, Undo2 } from "lucide-react";
import { type Kill, compactRupees, post, rupees, useApi, when } from "@/lib/api";
import { Badge, Button, Card, ErrorNote, Loading, Meter, PageTitle, Table } from "@/components/ui";
import { KillSwitch } from "@/components/kill-switch";
import { Confirm } from "@/components/confirm";
import { useToast } from "@/components/toast";

type Risk = {
  limits: { capital?: number; max_order_value?: number; max_position_value?: number; max_open_positions?: number;
    max_daily_loss?: number; max_orders_per_sec?: number; max_orders_per_day?: number; max_price_deviation?: number;
    allow_kinds?: string[]; allow_products?: string[] };
  usage: { exposure: number; largest_position: number; open_positions: number; orders_today: number; day_loss: number };
  blocked: { ts: string; kind: string; detail: string }[];
  kill: Kill;
};

const KIND: Record<string, { label: string; kind: "danger" | "warn" | "ok" | "muted" | "brand" }> = {
  blocked: { label: "blocked", kind: "danger" }, no_price: { label: "no price", kind: "warn" },
  kill_on: { label: "kill on", kind: "danger" }, kill_off: { label: "kill off", kind: "ok" },
  flatten_on: { label: "flatten requested", kind: "warn" }, flatten_off: { label: "flatten cancelled", kind: "muted" },
  flatten_done: { label: "flattened", kind: "brand" },
};

export default function RiskPage() {
  const { data, error, reload } = useApi<Risk>("/api/risk", 60_000);
  const [asking, setAsking] = useState<"on" | "off" | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const lim = data?.limits ?? {};
  const u = data?.usage;
  const flatten = !!data?.kill.flatten;

  async function setFlatten(on: boolean) {
    setAsking(null);
    setBusy(true);
    try {
      await post("/api/flatten", { on });
      toast(on ? "Flatten requested for the next open" : "Flatten cancelled");
    } catch (e) {
      toast(`Failed: ${e instanceof Error ? e.message : e}`, "error");
    }
    setBusy(false);
    reload();
  }

  return (
    <>
      <PageTitle sub="Hard limits every order passes through (they are code and config, never learned). Changing a limit needs a reviewed change to the repository.">
        Risk
      </PageTitle>
      <ErrorNote error={error} onRetry={reload} />
      {!data && !error ? <Loading rows={6} /> : data && u && (
        <div className="grid gap-5">
          <div className="grid gap-5 xl:grid-cols-3">
            <Card title="Usage against limits" className="xl:col-span-2">
              <div className="grid gap-5 md:grid-cols-2">
                <Meter label="Exposure" value={u.exposure} limit={lim.capital} format={compactRupees} />
                <Meter label="Largest position" value={u.largest_position} limit={lim.max_position_value} format={compactRupees} />
                <Meter label="Open positions" value={u.open_positions} limit={lim.max_open_positions} format={(v) => `${v}`} />
                <Meter label="Orders today" value={u.orders_today} limit={lim.max_orders_per_day} format={(v) => `${v}`} />
                <Meter label="Loss today" value={u.day_loss} limit={lim.max_daily_loss} format={rupees} />
              </div>
              <div className="mt-6 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
                <div><span className="text-muted-foreground">Max order value</span> · {rupees(lim.max_order_value)}</div>
                <div><span className="text-muted-foreground">Price check</span> · within {((lim.max_price_deviation ?? 0) * 100).toFixed(0)}% of last trade</div>
                <div><span className="text-muted-foreground">Order rate</span> · {lim.max_orders_per_sec ?? "–"} per second</div>
                <div><span className="text-muted-foreground">Allowed</span> · {(lim.allow_kinds ?? []).join(", ")} / {(lim.allow_products ?? []).join(", ")}</div>
                <div className="sm:col-span-2 text-muted-foreground">Hitting the daily loss limit turns the kill switch on by itself; only a person turns it off.</div>
              </div>
            </Card>
            <div className="grid content-start gap-5">
              <Card title="Kill switch"><KillSwitch kill={data.kill} onChange={reload} /></Card>
              <Card title="Flatten (paper)">
                <div className="space-y-4">
                  {flatten
                    ? <Badge kind="warn">Requested: sells everything at the next open run</Badge>
                    : <Badge kind="ok"><CheckCircle2 className="size-3.5" />Not requested</Badge>}
                  <p className="text-sm text-muted-foreground">Sells every paper position at the next open run (09:20 IST) and opens nothing new that day. Clears itself afterwards.</p>
                  {flatten
                    ? <Button variant="outline" onClick={() => setAsking("off")} disabled={busy}><Undo2 className="size-4" />Cancel flatten</Button>
                    : <Button variant="danger" onClick={() => setAsking("on")} disabled={busy}><LogOut className="size-4" />Flatten at next open</Button>}
                </div>
              </Card>
            </div>
          </div>
          <Card title="Blocked orders and risk events">
            <Table head={["Time", "Event", "Detail"]} rows={data.blocked.map((e) => [when(e.ts),
              <Badge key="k" kind={KIND[e.kind]?.kind ?? "muted"}>{KIND[e.kind]?.label ?? e.kind}</Badge>,
              <span key="d" className="whitespace-normal">{e.detail}</span>])} empty="Nothing blocked so far." />
          </Card>
        </div>
      )}
      <Confirm open={asking === "on"} title="Flatten the paper book?" confirmLabel="Flatten at next open" danger busy={busy}
        onConfirm={() => setFlatten(true)} onCancel={() => setAsking(null)}>
        At the next open run every paper position is sold and nothing new is bought that day. You can cancel before then.
      </Confirm>
      <Confirm open={asking === "off"} title="Cancel the flatten request?" confirmLabel="Cancel flatten" busy={busy}
        onConfirm={() => setFlatten(false)} onCancel={() => setAsking(null)}>
        The next open run trades normally from the model&apos;s signals.
      </Confirm>
    </>
  );
}
