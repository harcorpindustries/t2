"use client";

import Link from "next/link";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { Confirm } from "@/components/confirm";
import { Activity, BarChart3, Brain, LayoutDashboard, ListOrdered, LogOut, Newspaper } from "lucide-react";
import { cn } from "@/lib/cn";

const items = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/book", label: "Book", icon: BarChart3 },
  { href: "/signals", label: "Signals", icon: ListOrdered },
  { href: "/model", label: "Model", icon: Brain },
  { href: "/news", label: "News", icon: Newspaper },
  { href: "/system", label: "System", icon: Activity },
];

async function signOut() {
  await fetch("/api/logout", { method: "POST" });
  window.location.href = "/login";
}

export function Nav() {
  const path = usePathname();
  if (path.startsWith("/login") || path.startsWith("/breeze")) return null;
  return (
    <nav className="flex gap-1 overflow-x-auto md:flex-col">
      {items.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href}
            className={cn("flex h-11 items-center gap-3 rounded-md px-4 text-sm font-medium transition-colors",
              active ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

/** Red, at the bottom of the sidebar. Hidden on the sign-in and Breeze callback pages. */
export function SignOut() {
  const path = usePathname();
  const [asking, setAsking] = useState(false);
  if (path.startsWith("/login") || path.startsWith("/breeze")) return null;
  return (
    <>
      <button type="button" onClick={() => setAsking(true)}
        className="flex h-11 w-full items-center gap-3 rounded-md px-4 text-sm font-medium text-down hover:bg-down/15">
        <LogOut className="size-4" />
        Sign out
      </button>
      <Confirm open={asking} title="Sign out of T2?" confirmLabel="Sign out" danger
        onConfirm={signOut} onCancel={() => setAsking(false)}>
        You will need the dashboard password to sign in again. Paper trading keeps running on the server.
      </Confirm>
    </>
  );
}
