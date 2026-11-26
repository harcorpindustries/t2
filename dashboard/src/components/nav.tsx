"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Brain, LayoutDashboard, ListOrdered, Newspaper } from "lucide-react";
import { cn } from "@/lib/cn";

const items = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/book", label: "Book", icon: BarChart3 },
  { href: "/signals", label: "Signals", icon: ListOrdered },
  { href: "/model", label: "Model", icon: Brain },
  { href: "/news", label: "News", icon: Newspaper },
  { href: "/system", label: "System", icon: Activity },
];

export function Nav() {
  const path = usePathname();
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
    </nav>
  );
}
