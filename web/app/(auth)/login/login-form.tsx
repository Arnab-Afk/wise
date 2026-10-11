"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2, Mail } from "lucide-react";
import { GitHubIcon, GoogleIcon } from "@/components/tw/brand";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

async function post(path: string, body: unknown) {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ?? "Something went wrong. Try again.");
  return data;
}

export function LoginForm() {
  const params = useSearchParams();
  const next = params.get("next") ?? "";
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [error, setError] = useState(params.get("error") ?? "");
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [providers, setProviders] = useState<Record<string, boolean>>({});
  const boxes = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    fetch("/api/tw/v1/auth/providers").then((r) => r.json()).then(setProviders).catch(() => {});
  }, []);
  useEffect(() => {
    if (!cooldown) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const sendCode = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true); setError("");
    try {
      await post("/api/auth/otp/start", { email });
      setStep("code"); setDigits(Array(6).fill("")); setCooldown(30);
      setTimeout(() => boxes.current[0]?.focus(), 50);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (code: string) => {
    setBusy(true); setError("");
    try {
      const data = await post("/api/auth/otp/verify", { email, code });
      window.location.assign(next.startsWith("/") ? next : data.has_workspace ? "/incidents" : "/onboarding");
    } catch (err) {
      setError((err as Error).message);
      setDigits(Array(6).fill(""));
      boxes.current[0]?.focus();
      setBusy(false);
    }
  };

  const setDigit = (i: number, value: string) => {
    const clean = value.replace(/\D/g, "");
    if (clean.length > 1) { // pasted the whole code
      const all = clean.slice(0, 6).split("");
      const filled = [...all, ...Array(6 - all.length).fill("")];
      setDigits(filled);
      if (all.length === 6) verify(all.join(""));
      else boxes.current[all.length]?.focus();
      return;
    }
    const nextDigits = [...digits];
    nextDigits[i] = clean;
    setDigits(nextDigits);
    if (clean && i < 5) boxes.current[i + 1]?.focus();
    if (nextDigits.every(Boolean)) verify(nextDigits.join(""));
  };

  const oauth = (p: string) => `/api/auth/oauth/${p}${next ? `?next=${encodeURIComponent(next)}` : ""}`;

  return (
    <div className="w-full max-w-[400px] rounded-2xl border bg-background p-8 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      {step === "email" ? (
        <>
          <h1 className="text-[20px] font-medium tracking-tight">Sign in to Tracewise</h1>
          <p className="mt-1.5 text-muted-foreground">New here? Signing in creates your account.</p>
          <div className="mt-6 flex flex-col gap-2">
            {(["google", "github"] as const).map((p) => {
              const ready = providers[p];
              const label = p === "google" ? "Continue with Google" : "Continue with GitHub";
              return ready ? (
                <a key={p} href={oauth(p)}
                  className="flex h-10 items-center justify-center gap-2.5 rounded-lg border font-medium transition-colors hover:bg-muted">
                  {p === "google" ? <GoogleIcon /> : <GitHubIcon />}{label}
                </a>
              ) : (
                <span key={p} title="Not configured yet"
                  className="flex h-10 cursor-not-allowed items-center justify-center gap-2.5 rounded-lg border font-medium text-muted-foreground opacity-60">
                  {p === "google" ? <GoogleIcon /> : <GitHubIcon />}{label}
                </span>
              );
            })}
          </div>
          <div className="my-5 flex items-center gap-3 text-[12px] text-muted-foreground">
            <span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" />
          </div>
          <form onSubmit={sendCode} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-medium">Work email</span>
              <input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com" autoComplete="email"
                className="h-10 rounded-lg border px-3 outline-none focus:border-foreground/40" />
            </label>
            <Button type="submit" size="lg" className="h-10" disabled={busy}>
              {busy ? <Loader2 className="animate-spin" /> : <Mail />}Email me a sign-in code
            </Button>
          </form>
        </>
      ) : (
        <>
          <button onClick={() => { setStep("email"); setError(""); }} className="mb-4 flex items-center gap-1.5 text-[12.5px] text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-3.5" />Use a different email
          </button>
          <h1 className="text-[20px] font-medium tracking-tight">Check your email</h1>
          <p className="mt-1.5 text-muted-foreground">
            We sent a 6-digit code to <span className="font-medium text-foreground">{email}</span>. It expires in 10 minutes.
          </p>
          <div className="mt-6 flex justify-between gap-2" onPaste={(e) => { e.preventDefault(); setDigit(0, e.clipboardData.getData("text")); }}>
            {digits.map((d, i) => (
              <input key={i} ref={(el) => { boxes.current[i] = el; }} value={d} inputMode="numeric" autoComplete="one-time-code"
                maxLength={6} aria-label={`Digit ${i + 1}`} disabled={busy}
                onChange={(e) => setDigit(i, e.target.value)}
                onKeyDown={(e) => { if (e.key === "Backspace" && !d && i > 0) boxes.current[i - 1]?.focus(); }}
                className={cn("num h-12 w-full rounded-lg border text-center text-[20px] outline-none focus:border-foreground/50",
                  error && "border-bad/50")} />
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between text-[12.5px]">
            <span className="text-muted-foreground">{busy ? "Checking…" : "Didn't get it? Check spam."}</span>
            <button disabled={cooldown > 0 || busy} onClick={() => sendCode()}
              className="font-medium disabled:text-muted-foreground">
              {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
            </button>
          </div>
        </>
      )}
      {error && <p className="mt-4 rounded-lg bg-bad-soft px-3 py-2 text-[12.5px] text-bad">{error}</p>}
      <p className="mt-6 text-[11.5px] leading-relaxed text-muted-foreground">
        By continuing you agree to let Tracewise email you sign-in codes and incident notifications.
      </p>
    </div>
  );
}
