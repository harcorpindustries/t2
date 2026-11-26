import Link from "next/link";
import type { ReactNode } from "react";
import { RotateCw } from "lucide-react";
import { cn } from "@/lib/cn";

/** A content card: one box, soft ring instead of a border, nothing boxed inside it. */
export function Card({ title, action, children, className }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("min-w-0 rounded-xl bg-card p-5 text-card-foreground ring-1 ring-foreground/10 sm:p-6", className)}>
      {(title || action) && (
        <header className="mb-4 flex min-h-11 items-center justify-between gap-4">
          {title && <h2 className="text-base font-semibold sm:text-lg">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold leading-tight">{children}</h1>
      {sub && <p className="mt-1 text-sm text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** A plain figure: label + value. Not a card on its own. */
export function Stat({ label, value, tone, sub }: { label: string; value: ReactNode; tone?: "pos" | "neg"; sub?: ReactNode }) {
  return (
    <div className="min-w-32">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tabular-nums",
        tone === "pos" && "text-up", tone === "neg" && "text-down")}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function tone(v: number | null | undefined): "pos" | "neg" | undefined {
  if (v == null || v === 0) return undefined;
  return v > 0 ? "pos" : "neg";
}

export type BadgeKind = "muted" | "danger" | "ok" | "up" | "down" | "brand" | "warn";

/** Colored chips. Status kinds (ok/danger/warn) should carry an icon or a word, never color alone. */
export function Badge({ children, kind = "muted" }: { children: ReactNode; kind?: BadgeKind }) {
  return (
    <span className={cn("inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium",
      kind === "muted" && "bg-muted text-muted-foreground",
      kind === "danger" && "bg-down/15 text-down",
      kind === "ok" && "bg-good/15 text-good",
      kind === "warn" && "bg-warn/15 text-warn",
      kind === "up" && "bg-up/15 text-up",
      kind === "down" && "bg-down/15 text-down",
      kind === "brand" && "bg-brand/15 text-brand")}>{children}</span>
  );
}

export function Button({ children, onClick, variant = "primary", disabled, type = "button" }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "outline" | "ghost" | "danger";
  disabled?: boolean; type?: "button" | "submit";
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={cn("inline-flex h-11 items-center justify-center gap-2 rounded-md px-5 text-sm font-medium",
        "transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "disabled:pointer-events-none disabled:opacity-50",
        variant === "primary" && "bg-brand text-brand-foreground hover:bg-brand/80",
        variant === "outline" && "border border-border bg-background hover:bg-muted",
        variant === "ghost" && "hover:bg-muted",
        variant === "danger" && "bg-down/15 text-down hover:bg-down/25")}>
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props}
    className={cn("h-11 rounded-md border border-input bg-transparent px-4 text-base outline-none",
      "focus:border-ring focus:ring-[3px] focus:ring-ring/50", props.className)} />;
}

/** Rows separated by a tint on hover, not by lines. */
export function Table({ head, rows, empty = "Nothing yet" }: {
  head: ReactNode[]; rows: ReactNode[][]; empty?: string;
}) {
  if (!rows.length) return <p className="py-6 text-sm text-muted-foreground">{empty}</p>;
  return (
    <div className="-mx-2 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-medium text-muted-foreground">
            {head.map((h, i) => <th key={i} className="px-2 pb-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="rounded-lg hover:bg-muted/60">
              {r.map((c, j) => <td key={j} className="whitespace-nowrap px-2 py-2.5 tabular-nums first:rounded-l-lg last:rounded-r-lg">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="mb-6 flex items-center gap-3 rounded-lg bg-down/15 px-4 py-3 text-sm text-down">
      <span className="flex-1">Could not load: {error}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium hover:bg-down/15">
          <RotateCw className="size-3.5" />Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

/** Placeholder rows while a card's data loads. */
export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3 py-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className={cn("h-5", i % 2 ? "w-2/3" : "w-full")} />)}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-sm text-muted-foreground">{children}</p>;
}

/** A KPI tile: label, figure, optional note and a small trend line underneath. */
export function Tile({ label, value, tone, note, children, loading }: {
  label: string; value: ReactNode; tone?: "pos" | "neg"; note?: ReactNode; children?: ReactNode; loading?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {loading ? <Skeleton className="mt-2 h-7 w-24" /> : (
        <div className={cn("mt-1 truncate text-xl font-semibold tabular-nums sm:text-2xl",
          tone === "pos" && "text-up", tone === "neg" && "text-down")}>{value}</div>
      )}
      {note && <div className="mt-0.5 truncate text-xs text-muted-foreground">{note}</div>}
      {children && <div className="mt-2 h-8">{children}</div>}
    </div>
  );
}

/** Usage against a limit, with the numbers written out (color is never the only cue). */
export function Meter({ label, value, limit, format }: {
  label: string; value: number; limit: number | null | undefined; format: (v: number) => string;
}) {
  const frac = limit ? Math.min(1, Math.max(0, value / limit)) : 0;
  const level = frac >= 0.9 ? "danger" : frac >= 0.7 ? "warn" : "ok";
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {format(value)} <span className="opacity-70">of {limit != null ? format(limit) : "–"}</span>
          {limit ? <span className={cn("ml-2 font-medium", level === "danger" && "text-down", level === "warn" && "text-warn", level === "ok" && "text-good")}>{Math.round(frac * 100)}%</span> : null}
        </span>
      </div>
      <div className="h-2 rounded-sm bg-muted">
        <div className={cn("h-2 rounded-sm", level === "danger" ? "bg-down" : level === "warn" ? "bg-warn" : "bg-good")}
          style={{ width: `${Math.max(frac * 100, value > 0 ? 1.5 : 0)}%` }} />
      </div>
    </div>
  );
}

/** A row of filter chips (one choice). */
export function Chips<T extends string>({ value, options, onChange }: {
  value: T; options: { key: T; label: ReactNode }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button key={o.key} type="button" onClick={() => onChange(o.key)}
          className={cn("h-9 rounded-md px-3.5 text-sm font-medium transition-colors",
            value === o.key ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function SymbolLink({ symbol }: { symbol: string }) {
  return <Link href={`/stock?s=${encodeURIComponent(symbol)}`} className="font-medium hover:text-brand hover:underline">{symbol}</Link>;
}
