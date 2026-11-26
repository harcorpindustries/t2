"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
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
  if (path.startsWith("/login")) return null;
  return (
    <nav className="flex gap-1 overflow-x-auto md:flex-col">
      {items.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href}
            className={cn("flex h-11 items-center gap-3 rounded-full px-4 text-sm font-medium transition-colors",
              active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
      <button type="button" onClick={signOut}
        className="flex h-11 items-center gap-3 rounded-full px-4 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
        <LogOut className="size-4" />
        Sign out
      </button>
    </nav>
  );
}
