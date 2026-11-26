/** NSE cash-market clock in IST (weekdays; exchange holidays are not known here, so a holiday shows as
 *  "Open" with no trades — the paper trader detects that from the quotes and skips the day). */
export type MarketState = "pre-open" | "open" | "closed";

const OPEN = 9 * 60 + 15;
const PRE = 9 * 60;
const CLOSE = 15 * 60 + 30;

export function istNow(now = new Date()): Date {
  // a Date whose UTC fields read as IST wall-clock time
  return new Date(now.getTime() + (5 * 60 + 30) * 60_000);
}

export function marketStatus(now = new Date()): { state: MarketState; label: string; next: string; inMs: number } {
  const t = istNow(now);
  const dow = t.getUTCDay();
  const mins = t.getUTCHours() * 60 + t.getUTCMinutes();
  const weekday = dow >= 1 && dow <= 5;
  const msTo = (targetMins: number, addDays = 0) =>
    ((addDays * 24 * 60 + targetMins - mins) * 60 - t.getUTCSeconds()) * 1000;
  if (weekday && mins >= OPEN && mins < CLOSE) return { state: "open", label: "Market open", next: "closes", inMs: msTo(CLOSE) };
  if (weekday && mins >= PRE && mins < OPEN) return { state: "pre-open", label: "Pre-open", next: "opens", inMs: msTo(OPEN) };
  // next weekday open
  let add = weekday && mins < PRE ? 0 : 1;
  let d = (dow + add) % 7;
  while (d === 0 || d === 6) {
    add += 1;
    d = (dow + add) % 7;
  }
  return { state: "closed", label: "Market closed", next: "opens", inMs: msTo(OPEN, add) };
}

export function duration(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60_000));
  const d = Math.floor(m / 1440);
  const h = Math.floor((m % 1440) / 60);
  const mm = m % 60;
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${mm}m`;
  return `${mm}m`;
}
