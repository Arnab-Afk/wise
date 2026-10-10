"""Alert and deploy webhooks from monitoring, paging and CI tools, mapped to events and deploys.

Each parser takes the decoded body and returns (events, logs, deploys).
"""

import json
import re

from .model import first, log_from_dict, service_name, severity_of

LABEL_SERVICE_KEYS = ("service", "service_name", "app", "application", "app_kubernetes_io_name",
                      "container", "deployment", "job", "component", "namespace", "instance",
                      "host", "pod")


def service_from_labels(labels: dict, fallback: str = "unknown") -> str:
    for key in LABEL_SERVICE_KEYS:
        if labels.get(key):
            value = str(labels[key])
            if key == "instance":
                value = value.split(":")[0]
            if key == "pod":
                value = re.sub(r"-[a-z0-9]{8,10}-[a-z0-9]{5}$|-[a-z0-9]{5}$", "", value)
            return value
    return fallback


def tags_to_dict(tags) -> dict:
    """Datadog/Opsgenie style tags ("service:x", "env:prod") or a comma-separated string."""
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    out = {}
    for t in tags or []:
        if isinstance(t, str) and ":" in t:
            k, v = t.split(":", 1)
            out.setdefault(k.strip(), v.strip())
    return out


# ---------- alerting tools ----------

def alertmanager(body: dict, service=None):
    """Prometheus Alertmanager and Grafana Alerting (same webhook shape)."""
    events = []
    common = body.get("commonLabels") or {}
    for a in body.get("alerts", []):
        labels = {**common, **(a.get("labels") or {})}
        ann = a.get("annotations") or {}
        title = ann.get("summary") or ann.get("title") or labels.get("alertname") or "alert"
        if labels.get("alertname") and labels["alertname"] not in title:
            title = f"{labels['alertname']}: {title}"
        ends = a.get("endsAt")
        events.append({
            "service": service or service_from_labels(labels),
            "kind": "alert", "status": a.get("status", "firing"),
            "severity": severity_of(labels.get("severity") or labels.get("priority"), "error"),
            "title": title, "ts": a.get("startsAt"),
            "active_until": ends if ends and not ends.startswith("0001") else None,
            "fingerprint": a.get("fingerprint") or json.dumps(labels, sort_keys=True),
            "detail": {"labels": labels, "annotations": ann, "value": a.get("valueString"),
                       "url": a.get("generatorURL") or a.get("panelURL") or a.get("dashboardURL")},
        })
    return events, [], []


def datadog(body: dict, service=None):
    """Datadog monitor webhook (default payload or the template in our setup docs)."""
    title = body.get("title") or body.get("event_title") or "Datadog monitor"
    transition = (body.get("status") or body.get("alert_transition") or "").lower()
    if not transition:
        m = re.match(r"\[(\w[\w ]*)\]", title)
        transition = (m.group(1) if m else "triggered").lower()
    status = "resolved" if transition in ("recovered", "ok", "resolved") else "firing"
    tags = tags_to_dict(body.get("tags"))
    sev = body.get("priority") or ("warning" if "warn" in transition else "error")
    return [{
        "service": service or tags.get("service") or tags.get("app") or tags.get("kube_deployment")
        or tags.get("host") or "unknown",
        "kind": "alert", "status": status, "severity": severity_of(sev, "error"),
        "title": re.sub(r"^\[[^\]]+\]\s*", "", title), "ts": body.get("date") or body.get("last_updated"),
        "fingerprint": f"dd:{body.get('alert_id') or body.get('id') or title}",
        "detail": {"body": str(body.get("body") or "")[:2000], "url": body.get("url") or body.get("link"),
                   "tags": tags},
    }], [], []


def pagerduty(body: dict, service=None):
    ev = body.get("event") or {}
    data = ev.get("data") or {}
    etype = ev.get("event_type", "")
    if not etype.startswith("incident."):
        return [], [], []
    status = "resolved" if etype in ("incident.resolved",) else "firing"
    return [{
        "service": service or (data.get("service") or {}).get("summary") or "unknown",
        "kind": "alert", "status": status,
        "severity": "critical" if data.get("urgency") == "high" else severity_of(
            (data.get("priority") or {}).get("summary"), "error"),
        "title": data.get("title") or "PagerDuty incident", "ts": ev.get("occurred_at"),
        "fingerprint": f"pd:{data.get('id')}",
        "detail": {"url": data.get("html_url"), "number": data.get("number"), "event_type": etype},
    }], [], []


def opsgenie(body: dict, service=None):
    alert = body.get("alert") or {}
    action = (body.get("action") or "").lower()
    if action not in ("create", "close", "escalate", "addnote", "acknowledge", ""):
        return [], [], []
    tags = tags_to_dict(alert.get("tags"))
    details = alert.get("details") or {}
    return [{
        "service": service or details.get("service") or tags.get("service") or alert.get("entity")
        or alert.get("source") or "unknown",
        "kind": "alert", "status": "resolved" if action == "close" else "firing",
        "severity": severity_of(alert.get("priority"), "error"),
        "title": alert.get("message") or "Opsgenie alert",
        "fingerprint": f"og:{alert.get('alertId') or alert.get('alias')}",
        "detail": {"description": str(alert.get("description") or "")[:2000], "tags": alert.get("tags")},
    }], [], []


def _sentry_trace(event: dict) -> str | None:
    values = ((event.get("exception") or {}).get("values")
              or next((e.get("data", {}).get("values") for e in event.get("entries", [])
                       if e.get("type") == "exception"), None) or [])
    lines = ["Traceback (most recent call last):"] if values else []
    for exc in values:
        for f in ((exc.get("stacktrace") or {}).get("frames") or [])[-30:]:
            lines.append(f'  File "{f.get("filename") or f.get("absPath") or f.get("abs_path")}",'
                         f' line {f.get("lineno") or f.get("lineNo")}, in {f.get("function")}')
            if f.get("context_line"):
                lines.append(f"    {f['context_line'].strip()}")
        lines.append(f"{exc.get('type')}: {exc.get('value')}")
    return "\n".join(lines) if values else None


def sentry(body: dict, service=None):
    """Sentry issue alerts (integration platform and legacy webhook plugin) and issue webhooks."""
    data = body.get("data") or {}
    event = data.get("event") or body.get("event") or {}
    issue = data.get("issue") or {}
    action = (body.get("action") or "triggered").lower()
    project = (service or body.get("project_slug") or body.get("project_name")
               or (issue.get("project") or {}).get("slug") or event.get("project_slug")
               or str(body.get("project") or event.get("project") or "unknown"))
    title = event.get("title") or issue.get("title") or body.get("message") or "Sentry issue"
    level = event.get("level") or issue.get("level") or body.get("level") or "error"
    status = "resolved" if action in ("resolved", "ignored", "archived") else "firing"
    url = event.get("web_url") or issue.get("permalink") or issue.get("web_url") or body.get("url")
    events = [{"service": project, "kind": "alert", "status": status,
               "severity": severity_of(level, "error"), "title": title,
               "fingerprint": f"sentry:{issue.get('id') or event.get('issue_id') or body.get('id') or title}",
               "detail": {"url": url, "culprit": event.get("culprit") or body.get("culprit")}}]
    logs = []
    if status == "firing" and event:
        logs.append({"service": project, "ts": event.get("datetime") or event.get("timestamp"),
                     "level": "critical" if level == "fatal" else "error", "message": title,
                     "trace": _sentry_trace(event), "fields": {"sentry_url": url}})
    return events, logs, []


def cloudwatch(body: dict, service=None):
    """A CloudWatch alarm state change delivered by SNS (the Message field is JSON)."""
    msg = body.get("Message", body)
    if isinstance(msg, str):
        try:
            msg = json.loads(msg)
        except json.JSONDecodeError:
            return [], [], []
    if "AlarmName" not in msg:
        return [], [], []
    dims = {d.get("name") or d.get("Name"): d.get("value") or d.get("Value")
            for d in (msg.get("Trigger") or {}).get("Dimensions", [])}
    svc = service or next((dims[k] for k in ("ServiceName", "FunctionName", "TargetGroup",
                                              "LoadBalancer", "DBInstanceIdentifier", "ClusterName",
                                              "InstanceId", "ApiName", "QueueName") if dims.get(k)),
                          msg["AlarmName"])
    state = msg.get("NewStateValue")
    return [{"service": svc.split("/")[-2] if svc.startswith(("targetgroup/", "app/")) else svc,
             "kind": "alert", "status": "firing" if state == "ALARM" else "resolved",
             "severity": "error", "title": f"{msg['AlarmName']}: {msg.get('NewStateReason', '')}"[:500],
             "ts": msg.get("StateChangeTime"), "fingerprint": f"cw:{msg.get('AlarmArn') or msg['AlarmName']}",
             "detail": {"metric": (msg.get("Trigger") or {}).get("MetricName"),
                        "namespace": (msg.get("Trigger") or {}).get("Namespace"), "dimensions": dims,
                        "region": msg.get("Region")}}], [], []


def newrelic(body: dict, service=None):
    entities = body.get("impactedEntities") or (body.get("entitiesData") or {}).get("names") or []
    state = (body.get("state") or body.get("current_state") or "ACTIVATED").upper()
    return [{"service": service or (entities[0] if entities else None)
             or body.get("targets", [{}])[0].get("name") or "unknown",
             "kind": "alert", "status": "resolved" if state in ("CLOSED", "CLOSE") else "firing",
             "severity": severity_of(body.get("priority") or body.get("severity"), "error"),
             "title": body.get("title") or body.get("condition_name") or "New Relic issue",
             "fingerprint": f"nr:{body.get('issueId') or body.get('id') or body.get('incident_id')}",
             "detail": {"url": body.get("issueUrl") or body.get("incident_url"),
                        "policies": body.get("alertPolicyNames"),
                        "conditions": body.get("alertConditionNames")}}], [], []


def azure(body: dict, service=None):
    """Azure Monitor common alert schema."""
    ess = (body.get("data") or {}).get("essentials") or {}
    items = ess.get("configurationItems") or []
    target = (ess.get("alertTargetIDs") or [""])[0]
    return [{"service": service or (items[0] if items else target.rstrip("/").split("/")[-1]) or "unknown",
             "kind": "alert",
             "status": "resolved" if ess.get("monitorCondition") == "Resolved" else "firing",
             "severity": severity_of(ess.get("severity"), "error"),
             "title": ess.get("alertRule") or "Azure Monitor alert", "ts": ess.get("firedDateTime"),
             "fingerprint": f"az:{ess.get('alertId') or ess.get('originAlertId')}",
             "detail": {"description": ess.get("description"), "target": target,
                        "signal": ess.get("signalType")}}], [], []


def gcp(body: dict, service=None):
    """Google Cloud Monitoring webhook notification."""
    inc = body.get("incident") or {}
    labels = {**((inc.get("resource") or {}).get("labels") or {}),
              **((inc.get("metric") or {}).get("labels") or {}), **(inc.get("policy_user_labels") or {})}
    svc = (service or labels.get("service_name") or labels.get("container_name")
           or labels.get("function_name") or labels.get("module_id") or inc.get("resource_display_name")
           or inc.get("resource_name") or "unknown")
    return [{"service": svc, "kind": "alert",
             "status": "resolved" if inc.get("state") == "closed" else "firing",
             "severity": severity_of(inc.get("severity"), "error"),
             "title": f"{inc.get('policy_name') or 'GCP alert'}: {inc.get('summary', '')}"[:500],
             "ts": inc.get("started_at"), "fingerprint": f"gcp:{inc.get('incident_id')}",
             "detail": {"url": inc.get("url"), "condition": inc.get("condition_name"),
                        "labels": labels}}], [], []


def generic(body, service=None):
    """Anything else (Uptime Kuma, Zabbix, Checkly, Better Stack, custom scripts): a JSON object
    or a list of them with a title and a status; field names are guessed."""
    items = body if isinstance(body, list) else body.get("alerts") or [body]
    events = []
    for b in items:
        if not isinstance(b, dict):
            continue
        if "heartbeat" in b and "monitor" in b:  # Uptime Kuma
            hb, mon = b.get("heartbeat") or {}, b.get("monitor") or {}
            b = {"service": mon.get("name"), "title": b.get("msg") or hb.get("msg"),
                 "status": "resolved" if hb.get("status") == 1 else "firing",
                 "id": f"kuma:{mon.get('id')}", "url": mon.get("url")}
        labels = b.get("labels") or {}
        raw_status = str(first(b, "status", "state", "event", "action", "alert_status",
                               default="firing")).lower()
        status = "resolved" if re.search(
            r"resolv|recover|clos|inactive|\b(ok|up|normal|0)\b", raw_status) else "firing"
        events.append({
            "service": service or first(b, "service", "service_name", "app", "application",
                                        "component", "host", "hostname", "monitor", "name",
                                        default=None) or service_from_labels(labels),
            "kind": b.get("kind") or "alert", "status": status,
            "severity": severity_of(first(b, "severity", "priority", "level", "urgency"), "error"),
            "title": str(first(b, "title", "summary", "message", "msg", "description", "name",
                               default="alert"))[:500],
            "ts": first(b, "ts", "timestamp", "time", "startsAt", "started_at", "date"),
            "fingerprint": first(b, "fingerprint", "id", "alert_id", "incident_id", "key"),
            "detail": {k: v for k, v in b.items() if isinstance(v, (str, int, float, bool))},
        })
    return events, [], []


ALERT_PARSERS = {"alertmanager": alertmanager, "prometheus": alertmanager, "grafana": alertmanager,
                 "datadog": datadog, "pagerduty": pagerduty, "opsgenie": opsgenie, "sentry": sentry,
                 "cloudwatch": cloudwatch, "sns": cloudwatch, "newrelic": newrelic, "azure": azure,
                 "gcp": gcp, "generic": generic}


# ---------- deploy webhooks ----------

def deploy_github(body: dict, service=None):
    """GitHub `deployment_status` (state success) or `workflow_run` (completed, success) events."""
    if "deployment_status" in body:
        st, dep = body["deployment_status"], body.get("deployment") or {}
        if st.get("state") != "success":
            if st.get("state") in ("failure", "error"):
                return [{"service": service or (dep.get("payload") or {}).get("service")
                         or body.get("repository", {}).get("name") or "unknown",
                         "kind": "deploy_failed", "severity": "warning", "status": "firing",
                         "title": f"Deploy of {dep.get('sha', '')[:10]} to {dep.get('environment')} failed",
                         "detail": {"url": st.get("target_url")}}], [], []
            return [], [], []
        payload = dep.get("payload") if isinstance(dep.get("payload"), dict) else {}
        return [], [], [{"service": service or payload.get("service")
                         or body.get("repository", {}).get("name") or "unknown",
                         "sha": dep.get("sha"), "message": dep.get("description"),
                         "author": (dep.get("creator") or {}).get("login"),
                         "actor": "github", "reason": f"deployment to {dep.get('environment')}",
                         "deployed_at": st.get("created_at")}]
    run = body.get("workflow_run")
    if run and body.get("action") == "completed" and run.get("conclusion") == "success":
        commit = run.get("head_commit") or {}
        return [], [], [{"service": service or body.get("repository", {}).get("name") or "unknown",
                         "sha": run.get("head_sha"), "message": commit.get("message"),
                         "author": (commit.get("author") or {}).get("name"), "actor": "github",
                         "reason": f"workflow {run.get('name')}", "deployed_at": run.get("updated_at")}]
    return [], [], []


def deploy_gitlab(body: dict, service=None):
    if body.get("object_kind") != "deployment" or body.get("status") != "success":
        return [], [], []
    return [], [], [{"service": service or (body.get("project") or {}).get("name") or "unknown",
                     "sha": body.get("sha"), "message": body.get("commit_title"),
                     "author": (body.get("user") or {}).get("name"), "actor": "gitlab",
                     "reason": f"deployment to {body.get('environment')}",
                     "deployed_at": body.get("status_changed_at")}]


def deploy_vercel(body: dict, service=None):
    if body.get("type") not in ("deployment.succeeded", "deployment.ready", "deployment.promoted"):
        return [], [], []
    p = body.get("payload") or {}
    dep, meta = p.get("deployment") or {}, (p.get("deployment") or {}).get("meta") or {}
    return [], [], [{"service": service or (p.get("project") or {}).get("name") or p.get("name")
                     or dep.get("name") or "unknown",
                     "sha": meta.get("githubCommitSha") or meta.get("gitlabCommitSha") or dep.get("id"),
                     "message": meta.get("githubCommitMessage"),
                     "author": meta.get("githubCommitAuthorName"), "actor": "vercel",
                     "reason": f"deployment {p.get('target') or ''}".strip(),
                     "deployed_at": body.get("createdAt")}]


def deploy_generic(body: dict, service=None):
    """Argo CD notifications, Jenkins, Spinnaker, scripts: {service, sha|version, ...}."""
    items = body if isinstance(body, list) else [body]
    return [], [], [{"service": service or first(b, "service", "app", "application", "name") or "unknown",
                     "sha": str(first(b, "sha", "commit", "revision", "version", "image_tag", "tag",
                                      default="unknown")),
                     "prev_sha": first(b, "prev_sha", "previous_sha", "previous_version"),
                     "message": first(b, "message", "description", "commit_message"),
                     "author": first(b, "author", "user", "triggered_by"),
                     "actor": first(b, "actor", "tool", default="webhook"),
                     "reason": first(b, "reason", "environment", "env"),
                     "deployed_at": first(b, "deployed_at", "ts", "timestamp", "time")}
                    for b in items if isinstance(b, dict)]


DEPLOY_PARSERS = {"github": deploy_github, "gitlab": deploy_gitlab, "vercel": deploy_vercel,
                  "argocd": deploy_generic, "generic": deploy_generic}


def to_logs(records, service=None) -> list[dict]:
    return [log_from_dict(r, service) for r in records if isinstance(r, dict)]


__all__ = ["ALERT_PARSERS", "DEPLOY_PARSERS", "service_from_labels", "service_name", "to_logs"]
