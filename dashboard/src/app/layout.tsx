import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav, SignOut } from "@/components/nav";
import { ThemeToggle, Themes } from "@/components/theme";
import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = { title: "T2", description: "T2 trading system dashboard" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <Themes>
        <div className="md:flex">
          <aside className="flex flex-col bg-sidebar p-4 shadow-[2px_0_12px_-4px_rgba(0,0,0,0.12)] md:sticky md:top-0 md:h-screen md:w-64 md:shrink-0 md:p-6">
            <div className="mb-6 hidden items-center gap-3 px-4 md:flex">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/mascot.png" alt="T2 mascot" width={36} height={36} className="size-9" />
              <span className="text-lg font-semibold text-brand">T2</span>
            </div>
            <Nav />
            <div className="mt-4 space-y-1 md:mt-auto">
              <ThemeToggle />
              <p className="hidden px-4 py-2 text-xs text-muted-foreground md:block">
                Paper trading only. Not financial advice.
              </p>
              <SignOut />
            </div>
          </aside>
          <main className="min-w-0 flex-1 p-6 md:p-10">{children}</main>
        </div>
        </Themes>
      </body>
    </html>
  );
}
