import { cn } from "@/lib/utils";

/**
 * The Tracewise mark: a signal trace that dips (the incident) and returns to steady (recovered),
 * ending in a green point. Ink tile, so it holds up from favicon size to the hero.
 */
export function Mark({ size = 28, className, light }: { size?: number; className?: string; light?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={cn("shrink-0", className)} aria-hidden>
      <rect x="0.5" y="0.5" width="31" height="31" rx="7.5" fill={light ? "#F3F4F2" : "#15181A"}
        stroke="#FFFFFF" strokeOpacity={light ? 0 : 0.16} />
      <path d="M5 12H11.2L15 21.5L19.8 12H22.6" fill="none" stroke={light ? "#15181A" : "#F3F4F2"} strokeWidth="2.4"
        strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="25.8" cy="12" r="2.5" fill={light ? "#1F8F5F" : "#2BB673"} />
    </svg>
  );
}

export function Logo({ size = 28, className, inverted }: { size?: number; className?: string; inverted?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Mark size={size} light={inverted} />
      <span className={cn("font-sans font-semibold tracking-[-0.02em]", inverted ? "text-white" : "text-foreground")}
        style={{ fontSize: size * 0.62 }}>tracewise</span>
    </span>
  );
}
