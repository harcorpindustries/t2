import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "@/lib/cn";

/** Diverging bar from a center zero line: right/blue = expected to beat the others, left/red = to lag.
 *  Direction and the arrow carry the sign too, so color is never the only cue. */
export function ScoreBar({ score, max }: { score: number; max: number }) {
  const pct = Math.min(1, Math.abs(score) / (max || 1)) * 50;
  const up = score >= 0;
  return (
    <div className="flex items-center gap-2" title={`score ${score.toFixed(4)}`}>
      <div className="relative h-2.5 w-36 rounded-full bg-muted">
        <div className="absolute left-1/2 top-[-3px] h-[16px] w-[2px] -translate-x-1/2 rounded-full bg-muted-foreground/40" />
        <div
          className={cn("absolute top-0 h-2.5 rounded-full", up ? "bg-up" : "bg-down")}
          style={up ? { left: "50%", width: `${pct}%` } : { right: "50%", width: `${pct}%` }}
        />
      </div>
      {up ? <ArrowUp className="size-3.5 text-up" /> : <ArrowDown className="size-3.5 text-down" />}
      <span className="w-16 text-right font-mono text-xs tabular-nums text-muted-foreground">{score.toFixed(3)}</span>
    </div>
  );
}
