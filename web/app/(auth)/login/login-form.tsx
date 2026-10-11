"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";
import { GitHubIcon, GoogleIcon } from "@/components/tw/brand";
import { cn } from "@/lib/utils";

async function post(path: string, body: unknown) {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ?? "Something went wrong. Try again.");
  return data;
}

const field = "h-11 w-full rounded-lg border border-black/12 bg-white px-3.5 text-[14px] outline-none transition-colors placeholder:text-black/35 focus:border-black/50";

export function LoginForm({ mode }: { mode: "login" | "signup" }) {
  const params = useSearchParams();
  const next = params.get("next") ?? "";
  const [step, setStep] = useState<"email" | "code">("email");
  const [name, setName] = useState("");
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [error, setError] = useState(params.get("error") ?? "");
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [providers, setProviders] = useState<Record<string, boolean>>({});
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const signup = mode === "signup";
  const carry = next ? `?next=${encodeURIComponent(next)}` : "";

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
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const verify = async (code: string) => {
    setBusy(true); setError("");
    try {
      const data = await post("/api/auth/otp/verify", { email, code, name: signup ? name : undefined });
      window.location.assign(next.startsWith("/") ? next : data.has_workspace ? "/overview" : "/onboarding");
    } catch (err) {
      setError((err as Error).message); setDigits(Array(6).fill("")); boxes.current[0]?.focus(); setBusy(false);
    }
  };

  const setDigit = (i: number, value: string) => {
    const clean = value.replace(/\D/g, "");
    if (clean.length > 1) {
      const all = clean.slice(0, 6).split("");
      setDigits([...all, ...Array(6 - all.length).fill("")]);
      if (all.length === 6) verify(all.join("")); else boxes.current[all.length]?.focus();
      return;
    }
    const d = [...digits];
    d[i] = clean;
    setDigits(d);
    if (clean && i < 5) boxes.current[i + 1]?.focus();
    if (d.every(Boolean)) verify(d.join(""));
  };

  if (step === "code") {
    return (
      <div>
        <button onClick={() => { setStep("email"); setError(""); }} className="mb-8 flex items-center gap-1.5 text-[13px] text-black/55 hover:text-black">
          <ArrowLeft className="size-3.5" />Use a different email
        </button>
        <h1 className="display text-[44px] text-black">Check your email</h1>
        <p className="mt-3 text-[15px] text-black/60">We sent a 6-digit code to <span className="text-black">{email}</span>. It expires in 10 minutes.</p>
        <div className="mt-9 flex justify-between gap-2.5" onPaste={(e) => { e.preventDefault(); setDigit(0, e.clipboardData.getData("text")); }}>
          {digits.map((d, i) => (
            <input key={i} ref={(el) => { boxes.current[i] = el; }} value={d} inputMode="numeric" autoComplete="one-time-code"
              maxLength={6} aria-label={`Digit ${i + 1}`} disabled={busy}
              onChange={(e) => setDigit(i, e.target.value)}
              onKeyDown={(e) => { if (e.key === "Backspace" && !d && i > 0) boxes.current[i - 1]?.focus(); }}
              className={cn("num h-14 w-full rounded-lg border border-black/12 bg-white text-center text-[22px] outline-none focus:border-black/60",
                error && "border-bad/50")} />
          ))}
        </div>
        <div className="mt-5 flex items-center justify-between text-[13px]">
          <span className="text-black/50">{busy ? "Checking…" : "Didn't get it? Check spam."}</span>
          <button disabled={cooldown > 0 || busy} onClick={() => sendCode()} className="font-medium text-black disabled:text-black/35">
            {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
          </button>
        </div>
        {error && <p className="mt-5 rounded-lg bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">{error}</p>}
      </div>
    );
  }

  return (
    <div>
      <h1 className="display text-[48px] text-black">{signup ? "Create your account" : "Welcome back"}</h1>
      <p className="mt-3 text-[15px] text-black/60">
        {signup ? <>Already have an account? <Link href={`/login${carry}`} className="text-black underline underline-offset-4">Log in</Link></>
          : <>New to Tracewise? <Link href={`/signup${carry}`} className="text-black underline underline-offset-4">Create an account</Link></>}
      </p>
      <div className="mt-9 flex flex-col gap-2.5">
        {(["google", "github"] as const).map((p) => {
          const label = p === "google" ? "Continue with Google" : "Continue with GitHub";
          const icon = p === "google" ? <GoogleIcon /> : <GitHubIcon />;
          return providers[p] ? (
            <a key={p} href={`/api/auth/oauth/${p}${carry}`}
              className="flex h-11 items-center justify-center gap-2.5 rounded-lg border border-black/12 bg-white text-[14px] font-medium transition-colors hover:border-black/30">
              {icon}{label}
            </a>
          ) : (
            <span key={p} title="Not available yet" className="flex h-11 cursor-not-allowed items-center justify-center gap-2.5 rounded-lg border border-black/8 bg-white/60 text-[14px] text-black/35">
              {icon}{label}
            </span>
          );
        })}
      </div>
      <div className="my-7 flex items-center gap-3 text-[13px] text-black/45"><span className="h-px flex-1 bg-black/10" />or with email<span className="h-px flex-1 bg-black/10" /></div>
      <form onSubmit={sendCode} className="flex flex-col gap-4">
        {signup && (
          <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Name</span>
            <input className={field} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Lovelace" autoComplete="name" required /></label>
        )}
        <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Email</span>
          <input className={field} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="email" /></label>
        <button type="submit" disabled={busy}
          className="mt-2 flex h-11 items-center justify-center gap-2 rounded-lg bg-[#1c1b19] text-[14px] font-medium text-white transition-colors hover:bg-black disabled:opacity-60">
          {busy && <Loader2 className="size-4 animate-spin" />}{signup ? "Create account" : "Email me a sign-in code"}
        </button>
        <p className="text-[12.5px] text-black/45">No password: we email you a one-time code each time.</p>
      </form>
      {error && <p className="mt-5 rounded-lg bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">{error}</p>}
    </div>
  );
}
