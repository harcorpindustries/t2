"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/cn";

type Kind = "ok" | "error" | "info";
type Toast = { id: number; kind: Kind; text: string };

const ToastContext = createContext<(text: string, kind?: Kind) => void>(() => {});

/** Short confirmations ("Kill switch on") in the bottom-right corner; they disappear after 4 s. */
export function Toasts({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const push = useCallback((text: string, kind: Kind = "ok") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, kind, text }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      {mounted && createPortal(
        <div className="pointer-events-none fixed bottom-4 right-4 z-[1100] flex flex-col gap-2" role="status" aria-live="polite">
          {items.map((t) => {
            const Icon = t.kind === "ok" ? CheckCircle2 : t.kind === "error" ? AlertTriangle : Info;
            return (
              <div key={t.id} className="pointer-events-auto flex min-w-64 max-w-sm items-center gap-3 rounded-lg bg-card px-4 py-3 text-sm shadow-lg ring-1 ring-foreground/10">
                <Icon className={cn("size-4 shrink-0", t.kind === "ok" && "text-good", t.kind === "error" && "text-down",
                  t.kind === "info" && "text-brand")} />
                <span className="flex-1">{t.text}</span>
                <button type="button" aria-label="Dismiss" className="rounded p-1 text-muted-foreground hover:bg-muted"
                  onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}>
                  <X className="size-3.5" />
                </button>
              </div>
            );
          })}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
