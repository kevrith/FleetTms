"""An uptime check to run from cron or a systemd timer on a machine that is NOT the one being watched (so it can still say the server is down).

    python -m app.uptime_check --url https://api.example.com/ready --url https://app.example.com/ --state /var/lib/fleettms/uptime.json

Each run fetches every address. An address that fails `--fail-after` runs in a row raises one alert (not one every minute), a reminder is sent
every `--repeat-hours` while it stays down, and one message says when it is back. Alerts go to ALERT_EMAILS (using the SMTP settings) and to
ALERT_WEBHOOK_URL. The exit code is 1 while anything is down, so a monitoring system that only watches exit codes works too. For /ready the
body must also say `"ready": true`; its reasons are put in the alert."""

import argparse
import json
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path

import httpx

from app.config import settings


def judge(status_code: int, body: str, url: str) -> tuple[bool, str]:
    """Is this answer a healthy one? Returns (ok, why not)."""
    if status_code != 200:
        reason = f"answered {status_code}"
        if url.rstrip("/").endswith("/ready"):
            try:
                failing = json.loads(body).get("checks", {})
                reason += ": " + "; ".join(f"{k}: {v.get('reason', 'failing')}" for k, v in failing.items() if not v.get("ok"))
            except (ValueError, AttributeError):
                pass
        return False, reason
    if url.rstrip("/").endswith("/ready"):
        try:
            if json.loads(body).get("ready") is not True:
                return False, "answered 200 but not ready"
        except ValueError:
            return False, "answered 200 with something that is not JSON"
    return True, ""


def decide(entry: dict | None, ok: bool, why: str, now: float, *, fail_after: int = 2, repeat_hours: float = 6) -> tuple[dict, str | None]:
    """Updates one address's record and says what, if anything, to announce. `entry` is {failures, alerted_at, since}."""
    entry = dict(entry or {"failures": 0, "alerted_at": None, "since": None})
    if ok:
        was_alerted = entry["alerted_at"] is not None
        down_for = now - entry["since"] if entry["since"] is not None else 0
        entry.update(failures=0, alerted_at=None, since=None)
        return entry, (f"Back up after {down_for / 60:.0f} minutes." if was_alerted else None)
    entry["failures"] += 1
    entry["since"] = now if entry["since"] is None else entry["since"]
    if entry["failures"] < fail_after:
        return entry, None
    if entry["alerted_at"] is None:
        entry["alerted_at"] = now
        return entry, f"DOWN: {why}. It has failed {entry['failures']} checks in a row."
    if now - entry["alerted_at"] >= repeat_hours * 3600:
        entry["alerted_at"] = now
        return entry, f"STILL DOWN for {(now - entry['since']) / 3600:.1f} hours: {why}."
    return entry, None


def send_alert(subject: str, text: str) -> list[str]:
    """Delivers to every configured channel. Returns the channels that worked."""
    sent = []
    if settings.alert_webhook_url:
        try:
            httpx.post(settings.alert_webhook_url, json={"text": f"{subject}\n{text}"}, timeout=15).raise_for_status()
            sent.append("webhook")
        except httpx.HTTPError as e:
            print(f"webhook failed: {type(e).__name__}", file=sys.stderr)
    recipients = [a.strip() for a in settings.alert_emails.split(",") if a.strip()]
    if recipients and settings.smtp_host:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings.smtp_from or settings.smtp_user, ", ".join(recipients), subject
        message.set_content(text)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            sent.append("email")
        except (smtplib.SMTPException, OSError) as e:
            print(f"email failed: {type(e).__name__}", file=sys.stderr)
    return sent


def check(url: str, timeout: float = 10) -> tuple[bool, str]:
    try:
        res = httpx.get(url, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as e:
        return False, f"could not be reached ({type(e).__name__})"
    return judge(res.status_code, res.text, url)


def run(urls: list[str], state_path: Path, *, fail_after: int, repeat_hours: float, now: float | None = None, fetch=check, notify=send_alert) -> int:
    now = now if now is not None else time.time()
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    down = 0
    for url in urls:
        ok, why = fetch(url)
        state[url], message = decide(state.get(url), ok, why, now, fail_after=fail_after, repeat_hours=repeat_hours)
        down += not ok
        if message:
            notify(f"FleetTms: {url}", message)
            print(f"{url}: {message}")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1))
    return 1 if down else 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", action="append", required=True)
    p.add_argument("--state", default="uptime-state.json")
    p.add_argument("--fail-after", type=int, default=2)
    p.add_argument("--repeat-hours", type=float, default=6)
    args = p.parse_args()
    sys.exit(run(args.url, Path(args.state), fail_after=args.fail_after, repeat_hours=args.repeat_hours))


if __name__ == "__main__":
    main()
