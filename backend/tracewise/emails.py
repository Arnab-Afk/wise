"""Transactional email templates.

The layout follows the iac project's Vercel-style emails: white page, one bordered 465px card, a
centred wordmark, 24px heading, black button and a grey footer. Tables and inline styles only,
because Gmail and Outlook ignore <style> blocks and flexbox. Every email has a plain-text part
that says everything the HTML says.
"""

import os
from dataclasses import dataclass, field
from html import escape

from . import mail

WEB_URL = os.environ.get("TW_WEB_URL", "http://localhost:19103").rstrip("/")
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,Cantarell,"
        "'Helvetica Neue',sans-serif")
MONO = "SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"


@dataclass
class Email:
    subject: str
    heading: str            # HTML (already escaped)
    text: str               # the full plain-text body
    preview: str = ""
    paragraphs: list[str] = field(default_factory=list)   # HTML (already escaped)
    facts: list[tuple[str, str]] = field(default_factory=list)
    code: str | None = None
    button: tuple[str, str] | None = None                  # (label, url)
    footer: str = "You received this email because of activity on your Tracewise account."


def b(s) -> str:
    return f"<strong>{escape(str(s))}</strong>"


def render(e: Email) -> dict:
    parts = [f'<p style="margin:0 0 16px;font-size:14px;line-height:24px;color:#000000;">{p}</p>'
             for p in e.paragraphs]
    if e.code:
        parts.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            '<tr><td align="center" style="padding:8px 0 24px;">'
            f'<span style="display:inline-block;font-family:{MONO};font-size:32px;letter-spacing:10px;'
            'font-weight:600;color:#000000;background:#f6f6f6;border:1px solid #eaeaea;border-radius:6px;'
            f'padding:14px 22px 14px 32px;">{escape(e.code)}</span></td></tr></table>')
    if e.facts:
        rows = "".join(
            f'<tr><td style="padding:10px 14px;font-size:13px;line-height:20px;color:#666666;'
            f'{"border-top:1px solid #eaeaea;" if i else ""}">{escape(k)}</td>'
            f'<td align="right" style="padding:10px 14px;font-size:13px;line-height:20px;color:#000000;'
            f'{"border-top:1px solid #eaeaea;" if i else ""}">{escape(str(v))}</td></tr>'
            for i, (k, v) in enumerate(e.facts))
        parts.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
                     f'style="margin:8px 0 16px;border:1px solid #eaeaea;border-radius:5px;">{rows}</table>')
    if e.button:
        label, url = e.button
        parts.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            '<tr><td align="center" style="padding:16px 0 32px;">'
            f'<a href="{escape(url)}" style="display:inline-block;background:#000000;color:#ffffff;font-size:12px;'
            'font-weight:600;line-height:1;text-decoration:none;padding:13px 20px;border-radius:5px;">'
            f'{escape(label)}</a></td></tr></table>'
            '<p style="margin:0 0 16px;font-size:14px;line-height:24px;color:#000000;">or copy and paste this '
            f'URL into your browser: <a href="{escape(url)}" style="color:#2563eb;text-decoration:none;'
            f'word-break:break-all;">{escape(url)}</a></p>')
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{escape(e.subject)}</title>
</head>
<body style="margin:0;padding:0;background:#ffffff;">
<span style="display:none;max-height:0;overflow:hidden;opacity:0;color:#ffffff;">{escape(e.preview)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;">
<tr><td align="center" style="padding:40px 12px;">
  <table role="presentation" width="465" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:465px;border:1px solid #eaeaea;border-radius:5px;">
  <tr><td style="padding:20px;font-family:{FONT};color:#000000;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td align="center" style="padding-top:12px;">
      <span style="display:inline-block;width:24px;height:24px;line-height:24px;background:#000000;color:#ffffff;border-radius:6px;font-family:{MONO};font-size:13px;font-weight:600;text-align:center;vertical-align:middle;">T</span>
      <span style="font-family:{MONO};font-size:18px;color:#000000;vertical-align:middle;margin-left:6px;">tracewise</span>
    </td></tr>
    </table>
    <h1 style="margin:30px 0;padding:0;font-size:24px;font-weight:400;line-height:32px;text-align:center;color:#000000;">{e.heading}</h1>
    {"".join(parts)}
    <hr style="margin:26px 0;border:none;border-top:1px solid #eaeaea;width:100%;">
    <p style="margin:0;font-size:12px;line-height:24px;color:#666666;">{escape(e.footer)}</p>
  </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""
    return {"subject": e.subject, "text": e.text.strip() + "\n", "html": html}


def _send(to: str, template: str, e: Email) -> int:
    return mail.send(to, template, render(e))


ROLE_CAN = {
    "owner": "manage billing-free everything: members, projects, sources and coding agents",
    "admin": "invite people, manage projects, and connect sources and coding agents",
    "member": "see incidents, follow the agent live and trigger re-checks",
    "viewer": "see incidents and timelines (read-only)",
}


# ---------------------------------------------------------------- account

def sign_in_code(to: str, code: str, ip: str | None, minutes: int) -> int:
    return _send(to, "sign_in_code", Email(
        subject=f"{code} is your Tracewise sign-in code",
        preview=f"Your code is {code}. It expires in {minutes} minutes.",
        heading="Your sign-in code",
        paragraphs=["Enter this code on the Tracewise sign-in page to continue."],
        code=code,
        facts=[("Expires in", f"{minutes} minutes")] + ([("Requested from", ip)] if ip else []),
        footer="If you didn't try to sign in, ignore this email. Nobody can sign in without this code.",
        text=f"Your Tracewise sign-in code is {code}.\n\nIt expires in {minutes} minutes."
             + (f"\nRequested from {ip}." if ip else "")
             + "\n\nIf you didn't try to sign in, ignore this email."))


def welcome(to: str, name: str | None) -> int:
    hello = f"Welcome, {name.split()[0]}" if name else "Welcome to Tracewise"
    return _send(to, "welcome", Email(
        subject="Welcome to Tracewise",
        preview="Your on-call agent is ready. Here's how to get the first incident handled.",
        heading=escape(hello),
        paragraphs=[
            "Tracewise is an on-call engineer that runs on its own. When something breaks it finds the cause, "
            "fixes it, checks the fix held, and writes up what happened with the evidence.",
            "Three steps get you there:"],
        facts=[("1. Create a workspace", "for your team"), ("2. Connect a source", "Prometheus, Datadog, pm2…"),
               ("3. Connect a coding agent", "Claude or Cursor, for code fixes")],
        button=("Open Tracewise", f"{WEB_URL}/onboarding"),
        text=f"{hello}!\n\nTracewise is an on-call engineer that runs on its own: it finds the cause, fixes it, "
             "verifies the fix and writes it up.\n\n1. Create a workspace\n2. Connect a source (Prometheus, "
             f"Datadog, pm2...)\n3. Connect a coding agent (Claude or Cursor)\n\nStart here: {WEB_URL}/onboarding"))


def new_sign_in(to: str, method: str, ip: str | None, user_agent: str | None, when: str) -> int:
    device = (user_agent or "Unknown device")[:120]
    return _send(to, "new_sign_in", Email(
        subject="New sign-in to your Tracewise account",
        preview=f"Signed in with {method} from {ip or 'an unknown address'}.",
        heading="New sign-in",
        paragraphs=["Your Tracewise account was just signed in to from a device we haven't seen before."],
        facts=[("Method", method), ("When", when), ("IP address", ip or "unknown"), ("Device", device)],
        button=("Review your sessions", f"{WEB_URL}/settings/profile"),
        footer="If this wasn't you, sign out of that session from your profile and tell your workspace owner.",
        text=f"New sign-in to your Tracewise account.\n\nMethod: {method}\nWhen: {when}\nIP: {ip or 'unknown'}\n"
             f"Device: {device}\n\nIf this wasn't you, sign that session out: {WEB_URL}/settings/profile"))


def account_linked(to: str, provider: str) -> int:
    label = {"google": "Google", "github": "GitHub"}.get(provider, provider)
    return _send(to, "account_linked", Email(
        subject=f"{label} is now linked to your Tracewise account",
        preview=f"You can now sign in with {label}.",
        heading=f"{escape(label)} linked",
        paragraphs=[f"You can now sign in to Tracewise with {b(label)} as well as with an email code."],
        button=("View your profile", f"{WEB_URL}/settings/profile"),
        footer="If you didn't do this, sign out of all sessions from your profile.",
        text=f"{label} is now linked to your Tracewise account; you can sign in with it.\n\n"
             f"If you didn't do this, sign out of all sessions: {WEB_URL}/settings/profile"))


# ---------------------------------------------------------------- workspaces and teams

def workspace_created(to: str, workspace: str) -> int:
    return _send(to, "workspace_created", Email(
        subject=f"Your workspace {workspace} is ready",
        preview="Invite your team and connect your first source.",
        heading=f"{b(workspace)} is ready",
        paragraphs=[f"You're the owner of {b(workspace)}. Invite the people who share on-call with you, so they "
                    "can follow incidents live and get the agent's handovers."],
        button=("Invite your team", f"{WEB_URL}/settings/workspace"),
        text=f"Your workspace {workspace} is ready, and you're its owner.\n\n"
             f"Invite your team: {WEB_URL}/settings/workspace"))


def invite(to: str, inviter: str | None, workspace: str, role: str, url: str, days: int) -> int:
    who = inviter or "A teammate"
    return _send(to, "invite", Email(
        subject=f"{who} invited you to {workspace} on Tracewise",
        preview=f"Join {workspace} as {role}.",
        heading=f"Join {b(workspace)} on Tracewise",
        paragraphs=[f"{b(who)} invited you to the {b(workspace)} workspace as {b(role.title())}.",
                    f"As {role.title()} you can {escape(ROLE_CAN.get(role, ROLE_CAN['member']))}."],
        button=("Accept invitation", url),
        facts=[("Workspace", workspace), ("Role", role.title()), ("Expires in", f"{days} days")],
        footer=f"This invitation was meant for {to}. If you weren't expecting it, you can ignore this email.",
        text=f"{who} invited you to the {workspace} workspace on Tracewise as {role.title()}.\n\n"
             f"Accept: {url}\n\nThe invitation expires in {days} days."))


def invite_accepted(to: str, member: str, workspace: str, role: str) -> int:
    return _send(to, "invite_accepted", Email(
        subject=f"{member} joined {workspace}",
        preview=f"{member} accepted your invitation.",
        heading=f"{b(member)} joined {b(workspace)}",
        paragraphs=[f"{b(member)} accepted your invitation and joined as {b(role.title())}."],
        button=("View members", f"{WEB_URL}/settings/workspace"),
        text=f"{member} accepted your invitation and joined {workspace} as {role.title()}.\n\n"
             f"Members: {WEB_URL}/settings/workspace"))


def joined_workspace(to: str, workspace: str, role: str) -> int:
    return _send(to, "joined_workspace", Email(
        subject=f"You're in: {workspace} on Tracewise",
        preview=f"You joined {workspace} as {role}.",
        heading=f"Welcome to {b(workspace)}",
        paragraphs=[f"You joined {b(workspace)} as {b(role.title())}. You can "
                    f"{escape(ROLE_CAN.get(role, ROLE_CAN['member']))}."],
        button=("Open incidents", f"{WEB_URL}/incidents"),
        text=f"You joined {workspace} on Tracewise as {role.title()}.\n\nIncidents: {WEB_URL}/incidents"))


def role_changed(to: str, workspace: str, role: str, by: str | None) -> int:
    return _send(to, "role_changed", Email(
        subject=f"Your role in {workspace} is now {role.title()}",
        preview=f"{by or 'An admin'} changed your role.",
        heading=f"You're now {b(role.title())} in {b(workspace)}",
        paragraphs=[f"{b(by or 'An admin')} changed your role. You can now "
                    f"{escape(ROLE_CAN.get(role, ROLE_CAN['member']))}."],
        button=("Open Tracewise", f"{WEB_URL}/incidents"),
        text=f"{by or 'An admin'} changed your role in {workspace} to {role.title()}."))


def removed_from_workspace(to: str, workspace: str, by: str | None) -> int:
    return _send(to, "removed_from_workspace", Email(
        subject=f"You were removed from {workspace}",
        preview="You no longer have access to this workspace.",
        heading=f"Removed from {b(workspace)}",
        paragraphs=[f"{b(by or 'An admin')} removed you from {b(workspace)}. You no longer have access to its "
                    "incidents, sources or settings."],
        footer="If you think this was a mistake, contact the workspace owner.",
        text=f"{by or 'An admin'} removed you from {workspace} on Tracewise. You no longer have access to it."))


def added_to_team(to: str, workspace: str, team: str, projects: list[str], by: str | None) -> int:
    owns = f" The team is on call for {', '.join(projects)}, so you'll get its incident emails." if projects else ""
    return _send(to, "added_to_team", Email(
        subject=f"You were added to {team} in {workspace}",
        preview=f"{by or 'An admin'} added you to {team}.",
        heading=f"You're on {b(team)}",
        paragraphs=[f"{b(by or 'An admin')} added you to the {b(team)} team in {b(workspace)}.{escape(owns)}"],
        button=("View your teams", f"{WEB_URL}/teams"),
        text=f"{by or 'An admin'} added you to the {team} team in {workspace}.{owns}\n\n{WEB_URL}/teams"))


def project_created(to: str, workspace: str, project: str, by: str | None) -> int:
    return _send(to, "project_created", Email(
        subject=f"New project in {workspace}: {project}",
        preview=f"{by or 'Someone'} created {project}.",
        heading=f"New project: {b(project)}",
        paragraphs=[f"{b(by or 'A teammate')} created the project {b(project)} in {b(workspace)}. "
                    "Connect its sources so the agent can watch it."],
        button=("Connect sources", f"{WEB_URL}/sources"),
        text=f"{by or 'A teammate'} created the project {project} in {workspace}.\n\n"
             f"Connect its sources: {WEB_URL}/sources"))


def coding_agent_changed(to: str, workspace: str, provider: str, label: str, connected: bool, by: str | None) -> int:
    name = {"claude": "Claude Agent", "cursor": "Cursor Agent"}.get(provider, provider)
    verb = "connected" if connected else "disconnected"
    return _send(to, f"coding_agent_{verb}", Email(
        subject=f"Coding agent {verb} in {workspace}: {label}",
        preview=f"{by or 'An admin'} {verb} {name}.",
        heading=f"Coding agent {verb}",
        paragraphs=[f"{b(by or 'An admin')} {verb} {b(label)} ({escape(name)}) in {b(workspace)}."
                    + (" Tracewise will use it to write code fixes, each on its own branch with a regression test."
                       if connected else " Code fixes will be handed to a human until another agent is connected.")],
        button=("View coding agents", f"{WEB_URL}/agents"),
        footer="Coding agents use your team's API key. You get this email for every change, for security.",
        text=f"{by or 'An admin'} {verb} the coding agent {label} ({name}) in {workspace}.\n\n{WEB_URL}/agents"))


def source_connected(to: str, workspace: str, kind: str, name: str, by: str | None) -> int:
    return _send(to, "source_connected", Email(
        subject=f"{name} connected to {workspace}",
        preview=f"Tracewise is now reading {kind}.",
        heading=f"Source connected: {b(name)}",
        paragraphs=[f"{b(by or 'A teammate')} connected {b(name)} ({escape(kind)}). Tracewise checks the "
                    "credentials, then starts reading its errors, metrics and alerts."],
        button=("View sources", f"{WEB_URL}/sources"),
        text=f"{by or 'A teammate'} connected {name} ({kind}) to {workspace}.\n\n{WEB_URL}/sources"))


# ---------------------------------------------------------------- incidents

def approval_requested(to: str, incident: dict, action: str, reason: str, minutes: int) -> int:
    url = f"{WEB_URL}/incidents/{incident['id']}"
    return _send(to, "approval_requested", Email(
        subject=f"Approve? {action} (incident #{incident['id']})",
        preview=reason[:140],
        heading=f"The agent wants to: {b(action)}",
        paragraphs=[f"Incident #{incident['id']}: {escape(incident['title'])}",
                    f"{b('Why:')} {escape(reason)}",
                    f"Approve or reject it in Tracewise or Slack within {minutes} minutes. If nobody answers, the agent "
                    "won't do it and will hand over instead."],
        button=("Review and approve", url),
        footer="You get approval requests because you're on call for this project.",
        text=f"The agent wants to: {action}\nIncident #{incident['id']}: {incident['title']}\n\nWhy: {reason}\n\n"
             f"Approve or reject within {minutes} minutes: {url}"))


def incident_resolved(to: str, incident: dict, took: str, cost: str) -> int:
    url = f"{WEB_URL}/incidents/{incident['id']}"
    return _send(to, "incident_resolved", Email(
        subject=f"Resolved #{incident['id']}: {incident['title']}",
        preview=f"Fixed and verified in {took}.",
        heading=f"Resolved: {escape(incident['title'])}",
        paragraphs=[escape(incident.get("summary") or ""),
                    f"{b('Root cause:')} {escape(incident.get('root_cause') or '—')}",
                    f"{b('Fix:')} {escape(incident.get('fix') or '—')}"],
        facts=[("Incident", f"#{incident['id']}"), ("Services", ", ".join(incident.get("services") or [])),
               ("Time to recover", took), ("Agent cost", cost)],
        button=("Replay the incident", url),
        footer="You get resolution emails because your notifications are set to all incidents. Change it in your profile.",
        text=f"Resolved #{incident['id']}: {incident['title']}\n\n{incident.get('summary') or ''}\n\n"
             f"Root cause: {incident.get('root_cause') or '-'}\nFix: {incident.get('fix') or '-'}\n"
             f"Time to recover: {took}\nAgent cost: {cost}\n\nReplay: {url}"))


def incident_escalated(to: str, incident: dict, reason: str, handover: str) -> int:
    url = f"{WEB_URL}/incidents/{incident['id']}"
    return _send(to, "incident_escalated", Email(
        subject=f"Needs you: #{incident['id']} {incident['title']}",
        preview=reason[:140],
        heading=f"The agent needs a human for #{incident['id']}",
        paragraphs=[f"{b('Why it stopped:')} {escape(reason)}",
                    escape(handover).replace("\n", "<br>")],
        facts=[("Incident", f"#{incident['id']}"), ("Services", ", ".join(incident.get("services") or []))],
        button=("Open the handover", url),
        footer="You get escalations because you're in this workspace. Change it in your profile.",
        text=f"The agent needs a human for #{incident['id']}: {incident['title']}\n\nWhy it stopped: {reason}\n\n"
             f"{handover}\n\nOpen: {url}"))
