import { GlyphField } from "@/components/tw/glyph-field";

export function Wordmark({ dark }: { dark?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className={dark ? "flex size-7 items-center justify-center rounded-lg bg-white font-mono text-[13px] font-semibold text-black"
        : "flex size-7 items-center justify-center rounded-lg bg-foreground font-mono text-[13px] font-semibold text-background"}>T</span>
      <span className={dark ? "font-mono text-[15px] text-white" : "font-mono text-[15px]"}>tracewise</span>
    </span>
  );
}

/** Split screen, after the iac console: a dark brand panel and a light form panel. */
export function AuthShell({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <main className="grid h-dvh min-h-0 grid-rows-[minmax(0,1fr)] overflow-hidden lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-[#0b0b0c] text-white lg:flex">
        <div className="relative z-10 p-8"><Wordmark dark /></div>
        <div className="absolute inset-x-0 top-[22%] bottom-52 opacity-80"><GlyphField /></div>
        <blockquote className="relative z-10 border-t border-white/10 p-8">
          <p className="display max-w-[16ch] text-[42px] text-white">Production broke. It&apos;s already fixed.</p>
          <p className="mt-5 font-mono text-[11px] tracking-[0.12em] text-white/45 uppercase">
            Detects · investigates · fixes · verifies · writes it up
          </p>
        </blockquote>
      </aside>
      <section className="flex min-h-0 flex-col overflow-y-auto bg-[#fafaf8]">
        <div className="p-5 lg:hidden"><Wordmark /></div>
        <div className="flex flex-1 items-center justify-center px-5 py-12">
          <div className={wide ? "w-full max-w-[520px]" : "w-full max-w-[400px]"}>{children}</div>
        </div>
        <p className="px-5 pb-6 text-[12px] text-muted-foreground sm:px-8">
          By continuing you agree to let Tracewise email you sign-in codes and incident notifications.
        </p>
      </section>
    </main>
  );
}
