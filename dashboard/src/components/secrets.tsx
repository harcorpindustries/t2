"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, CircleDashed, FlaskConical, KeyRound, Search, ShieldCheck } from "lucide-react";
import { post, useApi, when } from "@/lib/api";
import { Badge, Button, Input } from "@/components/ui";
import { useToast } from "@/components/toast";

type Item = { key: string; group: string; label: string; help: string; secret: boolean; set: boolean;
  hint: string | null; updated_at: string | null };

/** A small form dialog (portal into <body>, Esc / outside click cancel). */
export function Modal({ open, title, children, onClose }: { open: boolean; title: string; children: ReactNode; onClose: () => void }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);
  if (!open || !mounted) return null;
  return createPortal(
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl bg-card p-6 text-card-foreground shadow-2xl ring-1 ring-foreground/10">
        <h2 className="mb-4 text-lg font-semibold">{title}</h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}

function Field({ label, children, note }: { label: string; children: ReactNode; note?: ReactNode }) {
  return (
    <label className="mb-4 block">
      <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {note && <span className="mt-1.5 block text-xs text-muted-foreground">{note}</span>}
    </label>
  );
}

function EditSecret({ item, onClose, onSaved }: { item: Item; onClose: () => void; onSaved: () => void }) {
  const [value, setValue] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [chats, setChats] = useState<{ id: string; name: string }[] | null>(null);
  const first = useRef<HTMLInputElement>(null);
  const toast = useToast();
  useEffect(() => first.current?.focus(), []);

  async function save(clear = false) {
    setBusy(true);
    setErr(null);
    try {
      await post("/api/secrets", { key: item.key, value: clear ? "" : value, password });
      toast(`${item.group}: ${item.label} ${clear ? "cleared" : "saved"}`);
      onSaved();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  async function findChats() {
    setErr(null);
    try {
      const r = await post<{ chats: { id: string; name: string }[] }>("/api/secrets/telegram-chats");
      setChats(r.chats);
      if (r.chats.length === 1) setValue(r.chats[0].id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); save(); }} autoComplete="off">
      <p className="mb-4 text-sm text-muted-foreground">{item.help}</p>
      <Field label={`New ${item.label.toLowerCase()}`} note={item.set ? "Replaces the saved value. The saved value is never shown." : undefined}>
        <div className="flex gap-2">
          <Input ref={first} type={item.secret ? "password" : "text"} value={value} onChange={(e) => setValue(e.target.value)}
            autoComplete="off" spellCheck={false} className="w-full font-mono" />
          {item.key === "TELEGRAM_CHAT_ID" && <Button variant="outline" onClick={findChats}><Search className="size-4" />Find my chat</Button>}
        </div>
      </Field>
      {chats && (
        <div className="mb-4 text-sm">
          {chats.length ? chats.map((c) => (
            <button key={c.id} type="button" onClick={() => setValue(c.id)}
              className="mr-2 rounded-md bg-muted px-2.5 py-1 font-mono text-xs hover:bg-brand/15">{c.id} {c.name && `(${c.name})`}</button>
          )) : <span className="text-muted-foreground">No chats yet: send your bot a message in Telegram, then try again.</span>}
        </div>
      )}
      <Field label="Your dashboard password" note="Needed for every change, so a borrowed session can't swap your keys.">
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" className="w-full" />
      </Field>
      {err && <p className="mb-4 rounded-md bg-down/15 px-3 py-2 text-sm text-down">{err}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        {item.set && <Button variant="ghost" onClick={() => save(true)} disabled={busy || !password}>Clear</Button>}
        <Button variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={busy || !value || !password}>Save</Button>
      </div>
    </form>
  );
}

/** API keys and secrets: status only, replace through a dialog, test without revealing. */
export function SecretsPanel() {
  const { data, reload } = useApi<{ items: Item[] }>("/api/secrets", 0);
  const [editing, setEditing] = useState<Item | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const toast = useToast();
  const groups = [...new Set((data?.items ?? []).map((i) => i.group))];

  async function test(key: string) {
    setTesting(key);
    try {
      const r = await post<{ ok: boolean; message: string }>("/api/secrets/test", { key });
      toast(r.message, r.ok ? "ok" : "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
    setTesting(null);
  }

  return (
    <div className="space-y-6">
      {groups.map((g) => {
        const items = (data?.items ?? []).filter((i) => i.group === g);
        return (
          <div key={g}>
            <div className="mb-2 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold">{g}</h3>
              <button type="button" onClick={() => test(items[0].key)} disabled={testing != null || !items.every((i) => i.set)}
                className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40">
                <FlaskConical className="size-3.5" />{testing === items[0].key ? "Testing…" : "Test"}
              </button>
            </div>
            <ul className="divide-y divide-border rounded-lg ring-1 ring-border">
              {items.map((i) => (
                <li key={i.key} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
                  <KeyRound className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{i.label} <code className="ml-1 font-mono text-[11px] text-muted-foreground">{i.key}</code></div>
                    <div className="text-xs text-muted-foreground">{i.updated_at ? `changed ${when(i.updated_at)}` : i.set ? "set from the server" : "not set"}</div>
                  </div>
                  {i.set
                    ? <Badge kind="ok"><CheckCircle2 className="size-3.5" />Set{i.hint ? ` · ${i.hint}` : ""}</Badge>
                    : <Badge kind="warn"><CircleDashed className="size-3.5" />Not set</Badge>}
                  <Button variant="outline" onClick={() => setEditing(i)}>{i.set ? "Replace" : "Add"}</Button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      <p className="flex items-start gap-2 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" />
        Saved on the server only (private settings file). Values can be replaced but never read back; each change needs
        your password, is logged and is announced on Telegram. The Cloudflare tunnel token stays server-only.
      </p>
      <Modal open={!!editing} title={editing ? `${editing.group}: ${editing.label}` : ""} onClose={() => setEditing(null)}>
        {editing && <EditSecret item={editing} onClose={() => setEditing(null)} onSaved={reload} />}
      </Modal>
    </div>
  );
}

/** Change the dashboard password (current one required). */
export function PasswordForm() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  const mismatch = again.length > 0 && next !== again;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await post("/api/password", { current: cur, new: next });
      toast("Dashboard password changed");
      setCur(""); setNext(""); setAgain("");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    }
    setBusy(false);
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-3">
      <Input type="password" placeholder="Current password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" />
      <Input type="password" placeholder="New (12+ characters)" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
      <Input type="password" placeholder="New again" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" />
      {(err || mismatch) && <p className="text-sm text-down sm:col-span-3">{mismatch ? "The new passwords don't match." : err}</p>}
      <div className="sm:col-span-3">
        <Button type="submit" disabled={busy || !cur || next.length < 12 || next !== again}>Change password</Button>
      </div>
    </form>
  );
}
