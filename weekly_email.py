"""Weekly profit email: last 7 days vs the 7 before, with a link to the dashboard.

Reads site/data.json (written by build_dashboard.py), so run that first.

Usage:
  python weekly_email.py --preview     # writes email_preview.html, sends nothing
  python weekly_email.py               # sends via Gmail (needs GMAIL_ADDRESS, GMAIL_APP_PASSWORD, REPORT_TO)
"""

import argparse
import html
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).parent
DEFAULT_URL = "https://riadmrad1992-blip.github.io/shopify-profit-dashboard/"

ROWS = [  # label, key, format, higher-is-better
    ("Revenue", "revenue", "money", True),
    ("Profit", "profit", "money", True),
    ("Ad spend", "ad_spend", "money", None),
    ("ROAS", "roas", "x", True),
    ("Orders", "orders", "int", True),
    ("Avg order value", "aov", "money2", True),
    ("Cost per order", "cost_per_order", "money2", False),
    ("Refund rate", "refund_rate", "pct", False),
]


def fmt(v, kind, cur):
    if v is None:
        return "–"
    sym = "$" if cur == "USD" else f"{cur} "
    return {"money": f"{'-' if v < 0 else ''}{sym}{abs(v):,.0f}",
            "money2": f"{'-' if v < 0 else ''}{sym}{abs(v):,.2f}",
            "x": f"{v:.2f}×", "int": f"{v:,}", "pct": f"{v * 100:.1f}%"}[kind]


def fmt_change(ch, good_up):
    if ch is None:
        return "–", "#7E8792"
    arrow = "▲" if ch >= 0 else "▼"
    if good_up is None or abs(ch) < 0.005:
        color = "#7E8792"
    else:
        color = "#1E8A5A" if (ch >= 0) == good_up else "#C0392B"
    return f"{arrow} {abs(ch) * 100:.0f}%", color


def build_email(data, url):
    s, cur = data["summary"], data["currency"]
    c, p, ch = s["current"], s["previous"], s["change"]
    first, last = data["days"][-7]["date"], data["days"][-1]["date"]
    subject = (f"{data['shop']}: {fmt(c['revenue'], 'money', cur)} revenue, "
               f"{fmt(c['profit'], 'money', cur)} profit last week")

    rows = []
    for label, key, kind, good_up in ROWS:
        text, color = fmt_change(ch.get(key), good_up)
        rows.append(
            f"<tr><td style='padding:8px 0;color:#4A5563'>{label}</td>"
            f"<td style='padding:8px 0;text-align:right;font-weight:600;color:#0E141B'>{fmt(c[key], kind, cur)}</td>"
            f"<td style='padding:8px 0;text-align:right;color:#7E8792'>{fmt(p[key], kind, cur)}</td>"
            f"<td style='padding:8px 0 8px 12px;text-align:right;color:{color}'>{text}</td></tr>")
    note = ("<p style='margin:16px 0 0;font-size:12px;color:#7E8792'>Ad spend is simulated: "
            "no ad account is connected to this test store.</p>") if data.get("spend_simulated") else ""

    body = f"""<!doctype html><html><body style="margin:0;background:#F3F1EC;font-family:Inter,Segoe UI,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F3F1EC;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background:#FFFFFF;border-radius:10px;overflow:hidden">
<tr><td style="background:#0E141B;padding:22px 28px;color:#F3F1EC">
  <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#7E8792">Weekly profit report</div>
  <div style="font-size:22px;font-weight:600;margin-top:4px">{html.escape(data['shop'])}</div>
  <div style="font-size:13px;color:#B9BDC3;margin-top:2px">{first} to {last}</div>
</td></tr>
<tr><td style="padding:22px 28px">
  <p style="margin:0 0 14px;font-size:15px;color:#0E141B">
    Profit was <b>{fmt(c['profit'], 'money', cur)}</b> on <b>{fmt(c['revenue'], 'money', cur)}</b> revenue,
    with a ROAS of <b>{fmt(c['roas'], 'x', cur)}</b>.</p>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;border-collapse:collapse">
    <tr><th style="text-align:left;font-size:12px;color:#7E8792;font-weight:500;padding-bottom:4px">Metric</th>
        <th style="text-align:right;font-size:12px;color:#7E8792;font-weight:500">Last 7 days</th>
        <th style="text-align:right;font-size:12px;color:#7E8792;font-weight:500">Prior 7</th>
        <th style="text-align:right;font-size:12px;color:#7E8792;font-weight:500">Change</th></tr>
    {''.join(rows)}
  </table>
  <p style="margin:22px 0 0"><a href="{html.escape(url)}" style="display:inline-block;background:#0E141B;color:#F3F1EC;text-decoration:none;padding:10px 16px;border-radius:6px;font-size:14px">Open the dashboard</a></p>
  {note}
</td></tr>
</table></td></tr></table></body></html>"""

    text = "\n".join([f"Weekly profit report: {data['shop']} ({first} to {last})", ""] +
                     [f"{label}: {fmt(c[key], kind, cur)} (prior {fmt(p[key], kind, cur)}, {fmt_change(ch.get(key), g)[0]})"
                      for label, key, kind, g in ROWS] + ["", f"Dashboard: {url}"])
    return subject, text, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="write email_preview.html instead of sending")
    args = ap.parse_args()
    data = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    url = os.environ.get("DASHBOARD_URL", DEFAULT_URL)
    subject, text, body = build_email(data, url)

    if args.preview:
        (ROOT / "email_preview.html").write_text(body, encoding="utf-8")
        print(f"Preview written: email_preview.html\nSubject: {subject}")
        return

    sender, password, to = (os.environ.get(k) for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "REPORT_TO"))
    if not (sender and password and to):
        sys.exit("Missing GMAIL_ADDRESS, GMAIL_APP_PASSWORD or REPORT_TO.")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    print(f"Sent: {subject} -> {to}")


if __name__ == "__main__":
    main()
