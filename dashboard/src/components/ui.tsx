import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** A content card: one box, soft ring instead of a border, nothing boxed inside it. */
export function Card({ title, action, children, className }: {
  title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("rounded-2xl bg-card p-6 text-card-foreground ring-1 ring-foreground/10", className)}>
      {(title || action) && (
        <header className="mb-4 flex min-h-11 items-center justify-between gap-4">
          {title && <h2 className="text-lg font-semibold">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-2xl font-semibold leading-tight">{children}</h1>
      {sub && <p className="mt-1 text-sm text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** A plain figure: label + value. Not a card on its own. */
export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "pos" | "neg" }) {
  return (
    <div className="min-w-36">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tabular-nums",
        tone === "pos" && "text-positive", tone === "neg" && "text-destructive")}>{value}</div>
    </div>
  );
}

export function tone(v: number | null | undefined): "pos" | "neg" | undefined {
  if (v == null || v === 0) return undefined;
  return v > 0 ? "pos" : "neg";
}

export function Badge({ children, kind = "muted" }: { children: ReactNode; kind?: "muted" | "danger" | "ok" }) {
  return (
    <span className={cn("inline-flex h-7 items-center rounded-full px-3 text-xs font-medium",
      kind === "muted" && "bg-muted text-muted-foreground",
      kind === "danger" && "bg-destructive/10 text-destructive",
      kind === "ok" && "bg-positive/10 text-positive")}>{children}</span>
  );
}

export function Button({ children, onClick, variant = "primary", disabled, type = "button" }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "outline" | "ghost" | "danger";
  disabled?: boolean; type?: "button" | "submit";
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={cn("inline-flex h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-medium",
        "transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "disabled:pointer-events-none disabled:opacity-50",
        variant === "primary" && "bg-primary text-primary-foreground hover:bg-primary/80",
        variant === "outline" && "border border-border bg-background hover:bg-muted",
        variant === "ghost" && "hover:bg-muted",
        variant === "danger" && "bg-destructive/10 text-destructive hover:bg-destructive/20")}>
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props}
    className={cn("h-11 rounded-[26px] border border-input bg-transparent px-4 text-base outline-none",
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

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <p className="mb-6 rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">Could not load: {error}</p>;
}
