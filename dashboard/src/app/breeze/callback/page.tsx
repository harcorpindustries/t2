"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui";

/** ICICI sends the browser here after the Breeze login, with ?apisession=N. Saving needs a dashboard sign-in. */
export default function BreezeCallback() {
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [msg, setMsg] = useState("Saving today's Breeze session…");

  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("apisession");
    const session = fromUrl ?? sessionStorage.getItem("t2-apisession");
    if (!session) {
      setState("error");
      setMsg("No session number arrived from ICICI. Start again from the dashboard.");
      return;
    }
    (async () => {
      const r = await fetch("/api/breeze/session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ apisession: session }),
      });
      if (r.status === 401) {
        sessionStorage.setItem("t2-apisession", session); // finish after signing in to the dashboard
        window.location.href = "/login?next=breeze";
        return;
      }
      sessionStorage.removeItem("t2-apisession");
      window.history.replaceState(null, "", "/breeze/callback"); // drop the number from the address bar
      if (r.ok) {
        setState("ok");
        setMsg("Breeze is connected for today. Paper trading and data collection will run.");
      } else {
        const body = await r.json().catch(() => ({}));
        setState("error");
        setMsg(body.detail ?? `Could not save the session (${r.status}). Log in to Breeze again.`);
      }
    })();
  }, []);

  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <div className="w-full max-w-md rounded-2xl bg-card p-8 ring-1 ring-foreground/10">
        <div className="mb-4 flex items-center gap-3">
          {state === "working" && <Loader2 className="size-5 animate-spin" />}
          {state === "ok" && <CheckCircle2 className="size-5 text-positive" />}
          {state === "error" && <XCircle className="size-5 text-destructive" />}
          <h1 className="text-lg font-semibold">Breeze login</h1>
        </div>
        <p className="mb-6 text-sm text-muted-foreground">{msg}</p>
        {state !== "working" && <Button onClick={() => (window.location.href = "/")}>Back to dashboard</Button>}
      </div>
    </div>
  );
}
