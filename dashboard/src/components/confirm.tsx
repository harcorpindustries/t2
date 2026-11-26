"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui";

/** In-page confirmation dialog. Cancel has focus on open (Enter never confirms by accident); Esc and a click
 *  outside cancel. Rendered into <body> through a portal: a dialog opened from inside a sticky/positioned
 *  container (the sidebar) would otherwise be trapped in that container's stacking context and charts on the
 *  page could paint over it. */
export function Confirm({ open, title, children, confirmLabel, danger, onConfirm, onCancel, busy }: {
  open: boolean; title: string; children?: ReactNode; confirmLabel: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void; busy?: boolean;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);
  useEffect(() => {  // keep the page behind from scrolling while the dialog is open
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);
  if (!open || !mounted) return null;
  return createPortal(
    <div className="fixed inset-0 z-[1000] backdrop-blur-[2px] flex items-center justify-center bg-black/50 p-4" onMouseDown={onCancel}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
        className="w-full max-w-md rounded-xl bg-card p-6 text-card-foreground shadow-[0_10px_15px_-3px_rgb(0_0_0/0.3),0_4px_6px_-4px_rgb(0_0_0/0.3)] ring-1 ring-foreground/10"
        onMouseDown={(e) => e.stopPropagation()}>
        <h2 id="confirm-title" className="text-lg font-semibold">{title}</h2>
        {children && <div className="mt-2 text-sm text-muted-foreground">{children}</div>}
        <div className="mt-6 flex justify-end gap-3">
          <button ref={cancelRef} type="button" onClick={onCancel}
            className="inline-flex h-10 items-center rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
            Cancel
          </button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy}>{confirmLabel}</Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
