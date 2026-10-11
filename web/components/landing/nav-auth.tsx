"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/** Log in / Start free, or Open console when there's already a session. Never redirects. */
export function NavAuth() {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    fetch("/api/tw/v1/auth/me", { credentials: "same-origin" })
      .then((r) => setSignedIn(r.ok))
      .catch(() => {});
  }, []);
  if (signedIn) return <Link href="/overview" className="lp-btn lp-btn-ink lp-btn-sm">Open console</Link>;
  return (
    <>
      <Link href="/login" className="lp-nav-login">Log in</Link>
      <Link href="/signup" className="lp-btn lp-btn-ink lp-btn-sm">Start free</Link>
    </>
  );
}
