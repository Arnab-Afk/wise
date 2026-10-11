import Link from "next/link";
import { Logo } from "@/components/tw/logo";
import { NavAuth } from "@/components/landing/nav-auth";
import "./landing.css";

const REPO = "https://github.com/Arnab-Afk/wise";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="lp">
      <a href="#main" className="lp-skip">Skip to content</a>
      <header className="lp-nav">
        <div className="lp-wrap lp-nav-row">
          <Link href="/" aria-label="Tracewise home"><Logo size={26} /></Link>
          <nav className="lp-nav-links" aria-label="Main">
            <Link href="/#how">How it works</Link>
            <Link href="/#approvals">Approvals</Link>
            <Link href="/#integrations">Integrations</Link>
            <Link href="/#faq">FAQ</Link>
          </nav>
          <div className="lp-nav-auth"><NavAuth /></div>
        </div>
      </header>
      <main id="main">{children}</main>
      <footer className="lp-foot">
        <div className="lp-wrap lp-foot-row">
          <div className="lp-foot-brand">
            <Logo size={22} />
            <p>The on-call agent that fixes production and shows its work.</p>
          </div>
          <nav className="lp-foot-cols" aria-label="Footer">
            <div>
              <h3>Product</h3>
              <Link href="/#how">How it works</Link>
              <Link href="/#integrations">Integrations</Link>
              <Link href="/#security">Security</Link>
              </div>
            <div>
              <h3>Company</h3>
              <a href={REPO}>GitHub</a>
              <a href="mailto:wise@arnabbhowmik.in">Contact</a>
              <Link href="/terms">Terms</Link>
              <Link href="/privacy">Privacy</Link>
            </div>
          </nav>
        </div>
        <div className="lp-wrap lp-foot-legal">© 2026 Tracewise</div>
      </footer>
    </div>
  );
}
