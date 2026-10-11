import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms of service | Tracewise" };

export default function Terms() {
  return (
    <section className="lp-legal">
      <div className="lp-wrap">
        <article>
          <h1 className="lp-h2">Terms of service</h1>
          <p className="lp-updated">Last updated October 12, 2026</p>
          <p>These terms cover your use of Tracewise. By creating a workspace you agree to them on behalf of yourself and your organisation.</p>
          <h2>The service</h2>
          <p>Tracewise watches the systems you connect, investigates incidents and, within the limits you set, takes actions such as rollbacks, feature flag changes and deploys. You decide per project whether those actions need approval.</p>
          <h2>Your responsibilities</h2>
          <ul>
            <li>Connect only systems you are authorised to operate.</li>
            <li>Keep ingest keys and API keys private, and rotate them if they leak.</li>
            <li>Review the action policy for each project. Actions taken under a policy you set are your responsibility.</li>
          </ul>
          <h2>Third-party AI providers</h2>
          <p>Investigations and fixes use the AI provider you connect, with your own API key. Their terms apply to that usage and they bill you for it directly.</p>
          <h2>Availability</h2>
          <p>We work hard to keep Tracewise running, but it is provided as is. Keep a human escalation path for anything Tracewise can&apos;t resolve.</p>
          <h2>Ending your use</h2>
          <p>Owners can delete projects and workspaces at any time. We delete their data within 30 days.</p>
          <h2>Contact</h2>
          <p>Questions about these terms: <a href="mailto:wise@arnabbhowmik.in">wise@arnabbhowmik.in</a>.</p>
        </article>
      </div>
    </section>
  );
}
