import { cn } from "@/lib/utils";

function hues(seed: string): [number, number] {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return [h % 360, (h % 360 + 40) % 360];
}

/** A person's photo, or a gradient seeded from their name (stable per person). */
export function Avatar({ name, src, size = 28, square, className }: {
  name: string; src?: string | null; size?: number; square?: boolean; className?: string;
}) {
  const [a, b] = hues(name || "?");
  const style = { width: size, height: size, fontSize: Math.max(10, size * 0.4) };
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt="" style={style} className={cn("shrink-0 object-cover", square ? "rounded-lg" : "rounded-full", className)} />;
  }
  return (
    <span style={{ ...style, background: `linear-gradient(135deg, hsl(${a} 75% 60%), hsl(${b} 80% 50%))` }}
      className={cn("flex shrink-0 items-center justify-center font-medium text-white", square ? "rounded-lg" : "rounded-full", className)}>
      {(name || "?").trim().slice(0, 1).toUpperCase()}
    </span>
  );
}
