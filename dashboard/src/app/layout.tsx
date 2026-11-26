import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav } from "@/components/nav";
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
          <aside className="bg-sidebar p-4 shadow-[2px_0_12px_-4px_rgba(0,0,0,0.12)] md:sticky md:top-0 md:h-screen md:w-64 md:shrink-0 md:p-6">
            <div className="mb-6 hidden px-4 text-lg font-semibold text-brand md:block">T2</div>
            <Nav />
            <div className="mt-2"><ThemeToggle /></div>
            <p className="mt-6 hidden px-4 text-xs text-muted-foreground md:block">
              Paper trading only. Not financial advice.
            </p>
          </aside>
          <main className="min-w-0 flex-1 p-6 md:p-10">{children}</main>
        </div>
        </Themes>
      </body>
    </html>
  );
}
