"use client";

import { useState } from "react";
import { LockKeyhole } from "lucide-react";
import { Button, Input } from "@/components/ui";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password }),
    });
    setBusy(false);
    if (r.ok) {
      window.location.href = "/";
      return;
    }
    const body = await r.json().catch(() => ({}));
    setError(body.detail ?? `Sign-in failed (${r.status})`);
  }

  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-card p-8 ring-1 ring-foreground/10">
        <div className="mb-6 flex items-center gap-3">
          <LockKeyhole className="size-5" />
          <h1 className="text-2xl font-semibold">T2</h1>
        </div>
        <label className="mb-2 block text-xs font-medium text-muted-foreground" htmlFor="pw">Password</label>
        <Input id="pw" type="password" autoComplete="current-password" autoFocus className="mb-4 w-full"
          value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
        <Button type="submit" disabled={busy || !password}>Sign in</Button>
      </form>
    </div>
  );
}
