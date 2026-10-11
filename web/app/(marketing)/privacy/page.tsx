import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy | Tracewise" };

export default function Privacy() {
  return (
    <section className="lp-legal">
      <div className="lp-wrap">
        <article>
          <h1 className="lp-h2">Privacy</h1>
          <p className="lp-updated">Last updated October 12, 2026</p>
          <h2>What we collect</h2>
          <ul>
            <li>Your account: name, email address and, if you sign in with Google or GitHub, the profile they share.</li>
            <li>Telemetry you send us: metrics, logs, alerts and deploy events from the services you connect.</li>
            <li>Incident records: what the agent looked at, what it concluded and what it did.</li>
          </ul>
          <h2>How we use it</h2>
          <p>Only to run Tracewise for your workspace: detecting and resolving incidents, sending you sign-in codes and incident notifications, and showing you the history. We don&apos;t sell data or use it for advertising.</p>
          <h2>Who else sees it</h2>
          <p>The AI provider you connect receives the context needed for an investigation or fix. Slack, Discord and email receive the notifications you set up. Nobody else.</p>
          <h2>Security</h2>
          <p>Ingest keys and sign-in codes are stored hashed. Chat and coding-agent tokens are encrypted at rest. Each project&apos;s data is isolated from every other project.</p>
          <h2>Retention and deletion</h2>
          <p>Deleting a project removes its telemetry and incidents. To delete your account entirely, email <a href="mailto:wise@arnabbhowmik.in">wise@arnabbhowmik.in</a>.</p>
        </article>
      </div>
    </section>
  );
}
