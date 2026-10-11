import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthShell } from "@/components/tw/auth-shell";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Log in · Tracewise" };

export default function LoginPage() {
  return (
    <AuthShell>
      <Suspense><LoginForm mode="login" /></Suspense>
    </AuthShell>
  );
}
