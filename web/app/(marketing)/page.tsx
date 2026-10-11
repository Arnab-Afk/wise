import type { Metadata } from "next";
import Link from "next/link";
import { Replay } from "@/components/landing/replay";
import { SlackIcon } from "@/components/tw/slack-icon";

export const metadata: Metadata = {
  title: "Tracewise: the on-call agent that fixes production",
  description:
    "Tracewise notices a failure, finds the change that caused it, rolls it back, ships a tested fix and writes it up. You approve anything that touches production.",
  openGraph: {
    title: "Production broke at 3:07 a.m. It was fixed by 3:10.",
    description: "The on-call agent that fixes production and shows its work.",
    images: ["/brand/og.png"],
  },
};

const EVIDENCE = "https://github.com/Arnab-Afk/wise/blob/main/docs/evidence/scenarios.md";

const STEPS = [
  {
    title: "Notice",
    body: "Tracewise watches error rates, latency, logs and alerts for every service you connect, and opens an incident the moment one goes wrong.",
    seen: "checkout errors jumped to 19%. Incident opened 7.7 s after the first failure.",
  },
  {
    title: "Investigate",
    body: "It reads recent deploys, logs and health across services, checks its memory of past incidents, and states a hypothesis with the evidence behind it.",
    seen: "Deploy bf60a94 shipped 2 s before the errors. TypeError at pricing.py:8. Same bug as incidents #6, #7 and #8.",
  },
  {
    title: "Act",
    body: "It takes the smallest safe step first: a rollback, a feature flag or a restart. Nothing runs against production without your approval unless you allow it.",
    seen: "Rolled checkout back to 5455ae3. Errors stopped within a minute.",
  },
  {
    title: "Fix forward",
    body: "Your coding agent writes the real fix with regression tests in your repo. Tracewise deploys it only after the tests pass, so you keep the feature.",
    seen: "Claude patched gift_wrap_fee and added 4 tests. 6 of 6 passed, then it shipped.",
  },
  {
    title: "Write it up",
    body: "Every incident ends with a timeline, the root cause, the evidence and each action taken, so the morning review takes two minutes.",
    seen: "Resolved in 3 m 09 s. Agent cost $0.15. Report in the console and in Slack.",
  },
];

const INTEGRATIONS = [
  { group: "Alerts", items: ["Prometheus Alertmanager", "Grafana", "Datadog", "PagerDuty", "Opsgenie", "Sentry", "New Relic", "CloudWatch", "Azure Monitor", "Google Cloud Monitoring"] },
  { group: "Logs and traces", items: ["OpenTelemetry", "Loki and Promtail", "Vector", "Fluent Bit", "Fluentd", "Splunk HEC", "Syslog", "Heroku drains", "CloudWatch Logs"] },
  { group: "Deploys", items: ["GitHub Actions", "GitLab", "Vercel", "Argo CD", "Any CI with one command"] },
  { group: "Runs on", items: ["Kubernetes", "Docker", "systemd", "pm2", "Plain log files"] },
  { group: "Writes fixes with", items: ["Claude Agent", "Cursor Agent"] },
  { group: "Talks to you in", items: ["Slack", "Discord", "Email"] },
];

const SECURITY = [
  { title: "You set the blast radius", body: "Per project, choose whether production actions wait for approval or run on their own. Requests expire after 10 minutes and the agent stands down." },
  { title: "It can only reach what you point it at", body: "Repositories and deploy targets are set by an admin. The agent can't add or change them." },
  { title: "Keys that can't leak back out", body: "Ingest keys are scoped to one project and stored hashed. Slack, Discord and coding-agent tokens are encrypted at rest." },
  { title: "Everything leaves a trail", body: "Every query, hypothesis, action and approval is recorded with who or what did it and why." },
];


const FAQ = [
  {
    q: "What does it do without asking?",
    a: "On new projects, nothing that touches production. It reads metrics, logs and deploys freely, but every rollback, flag change, restart or deploy waits for someone on your team to approve it. You can switch a project to run actions on its own once you trust it.",
  },
  {
    q: "What happens when it's wrong?",
    a: "Each action is checked afterwards. If errors don't fall, it says so, tries the next hypothesis or escalates to the on-call team with everything it found. It never retries an action someone rejected.",
  },
  {
    q: "Which AI does it use, and who pays for it?",
    a: "The investigation runs on Claude. Fixes are written by the coding agent you connect, Claude Agent or Cursor Agent, with your own API key, so model usage is billed to you directly by the provider. A typical incident costs about $0.11.",
  },
  {
    q: "Do I need to change my stack?",
    a: "No. Point your existing alerts, log shippers and deploy pipeline at Tracewise. If you have nothing set up, a single agent on the host picks up pm2, systemd, Docker, Kubernetes and log files.",
  },
  {
    q: "Does my code leave my infrastructure?",
    a: "Only the parts your coding agent reads to write a fix, sent to the provider you chose.",
  },
];

export default function Landing() {
  return (
    <>
      <section className="lp-hero">
        <div className="lp-wrap lp-hero-grid">
          <div className="lp-hero-copy">
            <h1 className="lp-display">Production broke at 3:07&nbsp;a.m. It was fixed by&nbsp;3:10.</h1>
            <p className="lp-lede">
              Tracewise is an on-call agent. It notices the failure, finds the change that caused it, rolls it back,
              ships a tested fix and writes up what happened, often before anyone is awake to read the page.
            </p>
            <div className="lp-hero-ctas">
              <Link href="/signup" className="lp-btn lp-btn-ink">Start free</Link>
              <Link href="#how" className="lp-btn lp-btn-line">See how it works</Link>
            </div>
            <p className="lp-hero-note">Connect your first service in about five minutes.</p>
          </div>
          <Replay />
        </div>
      </section>

      <section className="lp-proof" aria-label="Measured results">
        <div className="lp-wrap">
          <p>
            We broke a demo store 12 different times with bad configs, outages and buggy deploys. Tracewise resolved all 12.
            Median time to notice: <strong>6.5&nbsp;seconds</strong>. Median time to recover:{" "}
            <strong>1&nbsp;min&nbsp;32&nbsp;s</strong>. Agent cost: <strong>$0.11</strong> per incident.{" "}
            <a href={EVIDENCE}>See every run</a>
          </p>
        </div>
      </section>

      <section id="how" className="lp-section">
        <div className="lp-wrap">
          <h2 className="lp-h2">What happens when something breaks</h2>
          <p className="lp-sub">The same five steps your best engineer would take, in the order they&apos;d take them. On the right, what happened in incident #53.</p>
          <ol className="lp-seq">
            {STEPS.map((s, i) => (
              <li key={s.title} className="lp-seq-row">
                <span className="lp-seq-n">{i + 1}</span>
                <div>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                </div>
                <p className="lp-seq-seen">{s.seen}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="approvals" className="lp-section lp-band">
        <div className="lp-wrap lp-split">
          <div>
            <h2 className="lp-h2">You stay in charge of production</h2>
            <p className="lp-sub">
              Before it rolls back, flips a flag or deploys, Tracewise asks the on-call team in Slack or Discord, by email
              and in the console. One tap approves it. If nobody answers in 10 minutes, it stands down and escalates.
            </p>
            <ul className="lp-ticks">
              <li>Approvals are checked against your workspace roles</li>
              <li>Each request shows the evidence and what will change</li>
              <li>Switch a project to hands-off once you trust it</li>
            </ul>
          </div>
          <div className="lp-slack" role="img" aria-label="A Tracewise approval request in Slack with Approve and Reject buttons">
            <div className="lp-slack-chan"># oncall-checkout</div>
            <div className="lp-slack-msg">
              <span className="lp-slack-avatar"><SlackIcon className="size-4" /></span>
              <div className="lp-slack-body">
                <p className="lp-slack-who">Tracewise <span>APP</span> <time>3:07 a.m.</time></p>
                <p className="lp-slack-title">Approval needed: roll back checkout</p>
                <p>Errors started 2 s after deploy <code>bf60a94</code> &ldquo;Charge for gift wrapping at checkout&rdquo;. Rolling back to <code>5455ae3</code> should stop them.</p>
                <dl className="lp-slack-fields">
                  <div><dt>Incident</dt><dd>#53 checkout failing 19%</dd></div>
                  <div><dt>Confidence</dt><dd>97%</dd></div>
                </dl>
                <div className="lp-slack-btns">
                  <span className="lp-slack-btn is-primary">Approve</span>
                  <span className="lp-slack-btn">Reject</span>
                  <span className="lp-slack-btn">View incident</span>
                </div>
                <p className="lp-slack-ack">✓ Approved by you at 3:07 a.m.</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-wrap lp-split lp-split-flip">
          <div>
            <h2 className="lp-h2">A rollback buys time. The fix ends it.</h2>
            <p className="lp-sub">
              Rolling back means losing the feature you just shipped. So once production is stable, Tracewise hands the root cause
              to your coding agent, which patches it and writes tests for the exact failure. It deploys only when every test passes.
            </p>
            <p className="lp-sub">This is the commit Claude wrote during incident #53, unedited.</p>
          </div>
          <figure className="lp-diff" aria-label="The fix: services/checkout/pricing.py">
            <figcaption>services/checkout/pricing.py</figcaption>
            <pre>
              <code>
                <span className="lp-diff-ctx">{`  GIFT_WRAP_FEES = {"classic": 4.0, "kraft": 2.5}\n\n`}</span>
                <span className="lp-diff-del">{`- def gift_wrap_fee(gift_wrap: dict) -> float:\n-     return GIFT_WRAP_FEES[gift_wrap["style"]]\n`}</span>
                <span className="lp-diff-add">{`+ def gift_wrap_fee(gift_wrap: dict | None) -> float:\n+     if not isinstance(gift_wrap, dict):\n+         return 0.0\n+     style = gift_wrap.get("style")\n+     return GIFT_WRAP_FEES.get(style, 0.0) if isinstance(style, str) else 0.0\n`}</span>
              </code>
            </pre>
            <div className="lp-diff-tests">
              <span>tests/test_pricing.py</span>
              <span className="lp-diff-pass">6 passed in 0.04s</span>
            </div>
          </figure>
        </div>
      </section>

      <section id="integrations" className="lp-section lp-band">
        <div className="lp-wrap">
          <h2 className="lp-h2">Works with what you already run</h2>
          <p className="lp-sub">Point your existing alerts, logs and deploy pipeline at Tracewise. No new agent required, though there is one if you want it.</p>
          <div className="lp-integrations">
            {INTEGRATIONS.map((g) => (
              <div key={g.group}>
                <h3>{g.group}</h3>
                <ul>{g.items.map((i) => <li key={i}>{i}</li>)}</ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="security" className="lp-section">
        <div className="lp-wrap">
          <h2 className="lp-h2">Built to be trusted with production</h2>
          <div className="lp-security">
            {SECURITY.map((s) => (
              <div key={s.title}>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>


      <section id="faq" className="lp-section">
        <div className="lp-wrap lp-faq-grid">
          <h2 className="lp-h2">Questions</h2>
          <div className="lp-faq">
            {FAQ.map((f) => (
              <details key={f.q}>
                <summary>{f.q}</summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-final">
        <div className="lp-wrap">
          <h2 className="lp-display lp-final-title">Put Tracewise on call tonight.</h2>
          <p className="lp-lede">Connect one service, break something on staging, and watch it fix it.</p>
          <div className="lp-hero-ctas">
            <Link href="/signup" className="lp-btn lp-btn-paper">Start free</Link>
            <a href="mailto:wise@arnabbhowmik.in" className="lp-btn lp-btn-ghost">Talk to the founders</a>
          </div>
        </div>
      </section>
    </>
  );
}
