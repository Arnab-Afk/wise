import { Suspense } from "react";
import { LoginForm } from "./login-form";

export default function LoginPage() {
  // The form reads ?next and ?error, so it renders inside Suspense (Cache Components).
  return (
    <Suspense fallback={<div className="h-[420px] w-full max-w-[400px] rounded-2xl border bg-background" />}>
      <LoginForm />
    </Suspense>
  );
}
