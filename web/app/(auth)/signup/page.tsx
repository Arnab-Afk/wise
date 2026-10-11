import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthShell } from "@/components/tw/auth-shell";
import { LoginForm } from "../login/login-form";

export const metadata: Metadata = { title: "Create your account · Tracewise" };

export default function SignupPage() {
  return (
    <AuthShell>
      <Suspense><LoginForm mode="signup" /></Suspense>
    </AuthShell>
  );
}
