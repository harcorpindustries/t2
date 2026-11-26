"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Confirm } from "@/components/confirm";
import {
  Activity, BarChart3, Brain, LayoutDashboard, ListOrdered, LogOut, Newspaper, PanelLeftClose, PanelLeftOpen,
  Settings, ShieldAlert,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme";
import { cn } from "@/lib/cn";

export const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard, key: "o" },
  { href: "/book", label: "Book", icon: BarChart3, key: "b" },
  { href: "/signals", label: "Signals", icon: ListOrdered, key: "s" },
  { href: "/model", label: "Model", icon: Brain, key: "m" },
  { href: "/risk", label: "Risk", icon: ShieldAlert, key: "r" },
  { href: "/news", label: "News", icon: Newspaper, key: "n" },
  { href: "/system", label: "System", icon: Activity, key: "y" },
  { href: "/settings", label: "Settings", icon: Settings, key: "," },
];

export const chromeless = (path: string) => path.startsWith("/login") || path.startsWith("/breeze");

/** Label shown beside an icon-only control when the sidebar is collapsed. */
function Tip({ show, children }: { show: boolean; children: React.ReactNode }) {
  if (!show) return null;
  return (
    <span role="tooltip" className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background opacity-0 shadow-md transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
      {children}
    </span>
  );
}

/** The sidebar. Collapsed = a thin rail of icons with a label on hover; the choice is remembered per browser.
 *  On phones it is a drawer opened from the top bar. */
export function Sidebar({ collapsed, onToggle, mobileOpen, onClose }: {
  collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onClose: () => void;
}) {
  const path = usePathname();
  useEffect(() => onClose(), [path, onClose]);
  if (chromeless(path)) return null;
  const rail = collapsed && !mobileOpen;
  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-40 bg-black/50 md:hidden" onClick={onClose} aria-hidden />}
      <aside
        className={cn(
          "z-50 flex flex-col bg-sidebar shadow-[2px_0_12px_-4px_rgba(0,0,0,0.12)] transition-[width] duration-200",
          "fixed inset-y-0 left-0 w-64 p-4 md:sticky md:top-0 md:h-screen md:shrink-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
          rail ? "md:w-16 md:px-2 md:py-4" : "md:w-64 md:p-5",
        )}
      >
        <div className={cn("mb-6 flex items-center gap-3", rail ? "justify-center" : "px-3")}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/mascot.png" alt="T2 mascot" width={36} height={36} className="size-9 shrink-0" />
          {!rail && <span className="text-lg font-semibold text-brand">T2</span>}
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link key={href} href={href} aria-label={label}
                className={cn("group relative flex h-11 items-center gap-3 rounded-md text-sm font-medium transition-colors",
                  rail ? "justify-center px-0" : "px-3",
                  active ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
                <Icon className="size-[18px] shrink-0" />
                {!rail && label}
                <Tip show={rail}>{label}</Tip>
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto space-y-1 pt-4">
          <ThemeToggle compact={rail} />
          {!rail && <p className="px-3 py-2 text-xs text-muted-foreground">Paper trading only. Not financial advice.</p>}
          <SignOut compact={rail} />
          <button type="button" onClick={onToggle} aria-label={rail ? "Expand sidebar" : "Collapse sidebar"}
            className={cn("group relative hidden h-11 w-full items-center gap-3 rounded-md text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground md:flex",
              rail ? "justify-center" : "px-3")}>
            {rail ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
            {!rail && <span className="flex-1 text-left">Collapse</span>}
            {!rail && <kbd className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">⌘B</kbd>}
            <Tip show={rail}>Expand (⌘B)</Tip>
          </button>
        </div>
      </aside>
    </>
  );
}

async function signOut() {
  await fetch("/api/logout", { method: "POST" });
  window.location.href = "/login";
}

/** Red, at the bottom of the sidebar. The command palette opens the same confirmation (event "t2:signout"). */
export function SignOut({ compact }: { compact?: boolean }) {
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    const open = () => setAsking(true);
    window.addEventListener("t2:signout", open);
    return () => window.removeEventListener("t2:signout", open);
  }, []);
  return (
    <>
      <button type="button" onClick={() => setAsking(true)} aria-label="Sign out"
        className={cn("group relative flex h-11 w-full items-center gap-3 rounded-md text-sm font-medium text-down hover:bg-down/15",
          compact ? "justify-center" : "px-3")}>
        <LogOut className="size-[18px] shrink-0" />
        {!compact && "Sign out"}
        <Tip show={!!compact}>Sign out</Tip>
      </button>
      <Confirm open={asking} title="Sign out of T2?" confirmLabel="Sign out" danger
        onConfirm={signOut} onCancel={() => setAsking(false)}>
        You will need the dashboard password to sign in again. Paper trading keeps running on the server.
      </Confirm>
    </>
  );
}
