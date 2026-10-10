#!/usr/bin/env python3
"""
Daily summary: collect the latest data from every emailer repo into one file,
and email a single morning digest.

    python daily_summary.py collect
        -> runs every source listed in config.json -> "summary_sources" and
           writes data/summary.json (also drawn by the dashboard pages)

    python daily_summary.py send
        -> builds the summary email from data/summary.json and sends it

    python daily_summary.py preview
        -> writes the email to email_preview.html without sending it

    python daily_summary.py sources
        -> lists the sources you can use in config.json

Sources live in summary_sources.py and return generic blocks (charts, tiles,
tables; see summary_core.py), so the email and the dashboard draw a new
source without any change. Each section degrades gracefully if its data
isn't there yet.

Environment:
  GITHUB_OWNER        owner of the emailer repos (default: tuongphanbase)
  GH_READ_TOKEN       optional; a token that can read the emailer repos. Needed
                      once those repos are private (public repos need none).
  GMAIL_ADDRESS, GMAIL_APP_PASSWORD, SUMMARY_RECIPIENT   for `send`
  DASHBOARD_URL       optional link at the bottom of the email
  TIMEZONE            optional, default Asia/Ho_Chi_Minh
"""

import json
import os
import smtplib
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from zoneinfo import ZoneInfo

import summary_sources  # noqa: F401  (registers the sources)
from summary_core import OWNER, SOURCES

TZ = ZoneInfo(os.environ.get("TIMEZONE") or "Asia/Ho_Chi_Minh")
SUMMARY_FILE = os.path.join("data", "summary.json")
CONFIG_FILE = "config.json"
DEFAULT_SOURCES = ["gold", "currency", "stocks", "interest", "tech", "phones"]


def load_source_config(path=CONFIG_FILE):
    """[{"id", "source", "title", "icon", "options"}] from config.json -> summary_sources.
    An entry is a source id ("gold") or an object {"source": "csv_history", "id": ..., "title": ..., ...}."""
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f).get("summary_sources") or DEFAULT_SOURCES
    except (OSError, ValueError):
        entries = DEFAULT_SOURCES
    out = []
    for e in entries:
        e = {"source": e} if isinstance(e, str) else dict(e)
        name = e.pop("source", None) or e.get("id")
        if name not in SOURCES:
            print(f"  unknown source {name!r} in {path}; run `python daily_summary.py sources`", file=sys.stderr)
            continue
        reg = SOURCES[name]
        out.append({"id": e.pop("id", name), "source": name, "title": e.pop("title", reg["title"]),
                    "icon": e.pop("icon", reg["icon"]), "options": e})
    return out


def run_source(entry):
    try:
        section = entry["fn"](entry["options"])
    except Exception as e:  # one broken source must not sink the others
        section = {"ok": False, "reason": f"lỗi: {e}"}
    return {"id": entry["id"], "title": entry["title"], "icon": entry["icon"], **section}


def cmd_collect():
    entries = [{**e, "fn": SOURCES[e["source"]]["fn"]} for e in load_source_config()]
    with ThreadPoolExecutor(max_workers=8) as pool:  # sources fetch in parallel
        sections = list(pool.map(run_source, entries))
    for s in sections:
        print(f"  {s['id']}: {'ok' if s.get('ok') else s.get('reason')}")
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "owner": OWNER, "sections": sections}
    os.makedirs(os.path.dirname(SUMMARY_FILE), exist_ok=True)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"Wrote {SUMMARY_FILE}")


# --- Email --------------------------------------------------------------------

def fmt_num(v, decimals=0):
    if v is None:
        return "—"
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")  # Vietnamese style 1.234.567,89


def fmt_change(pct, note=None):
    if pct is None:
        return f'<span style="color:#888;">{escape(note or "—")}</span>'
    if pct > 0:
        return f'<span style="color:#1E8A4C;">&#9650; {pct:+.2f}%</span>'
    if pct < 0:
        return f'<span style="color:#C13C30;">&#9660; {pct:+.2f}%</span>'
    return '<span style="color:#888;">0,00%</span>'


TH = 'style="text-align:left; padding:6px 8px; font-size:12px; color:#6E7178; font-weight:600; border-bottom:1px solid #E1E1E4;"'
THR = TH.replace('text-align:left;', 'text-align:right;')
TD = 'style="padding:6px 8px; font-size:14px; color:#17181A; border-bottom:1px solid #F0F0F2;"'
TDR = 'style="padding:6px 8px; font-size:14px; color:#17181A; border-bottom:1px solid #F0F0F2; text-align:right; white-space:nowrap;"'


def email_table(headers, rows, right_cols=()):
    head = "".join(f"<th {THR if i in right_cols else TH}>{escape(h)}</th>" for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f"<td {TDR if i in right_cols else TD}>{c}</td>" for i, c in enumerate(r)) + "</tr>"
        for r in rows)
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse; margin:6px 0 4px;"><tr>{head}</tr>{body}</table>')


def email_section(title, inner, note=None):
    note_html = f'<div style="font-size:12px; color:#888; margin-top:4px;">{escape(note)}</div>' if note else ""
    return (f'<div style="background:#fff; border:1px solid #E1E1E4; border-radius:12px; padding:16px; margin:12px 0;">'
            f'<h2 style="margin:0 0 6px; font-size:16px; color:#17181A;">{title}</h2>{inner}{note_html}</div>')


def unavailable(s):
    return f'<p style="color:#888; font-size:13px; margin:4px 0;">Chưa có dữ liệu ({escape(s.get("reason", "?"))}).</p>'


def fmt_cell(value, kind):
    """One table cell as email HTML, by column kind."""
    if kind == "change":
        return fmt_change(value)
    if kind == "link":
        text, url = (value + ["", ""])[:2] if isinstance(value, list) else (value, "")
        return f'<a href="{escape(url)}" style="color:#17181A;">{escape(str(text))}</a>' if url else escape(str(text))
    if kind == "num" and isinstance(value, (int, float)):
        return fmt_num(value, 2 if abs(value) < 100 and value != int(value) else 0)
    return escape(str(value)) if value not in (None, "") else "—"


def block_html(block):
    """Email HTML for one generic block. Charts become a table of the latest
    values (email clients cannot draw them); the dashboard draws the chart."""
    kind = block["type"]
    if kind == "table":
        cols = block["columns"]
        right = tuple(i for i, c in enumerate(cols) if c["kind"] in ("num", "change"))
        cap = f'<div style="font-size:13px; color:#6E7178; margin-top:8px;">{escape(block["caption"])}:</div>' if block.get("caption") else ""
        return cap + email_table([c["label"] for c in cols],
                                 [[fmt_cell(v, c["kind"]) for v, c in zip(r, cols)] for r in block["rows"]], right)
    if kind == "tiles":
        return email_table(["", block.get("unit") or "Giá trị", "Thay đổi"],
                           [[escape(i["label"]), fmt_cell(i["value"], "num"), fmt_change(i.get("change_pct"), i.get("note"))]
                            for i in block["items"]], (1, 2))
    return ""  # charts: shown on the dashboard only


def build_email(summary):
    parts, text = [], []
    for s in summary.get("sections", []):
        title = f'{escape(s.get("icon") or "")} {escape(s["title"])}'.strip()
        if not s.get("ok"):
            parts.append(email_section(title, unavailable(s)))
            continue
        inner = "".join(block_html(b) for b in s.get("blocks", []))
        if not inner:
            inner = f'<p style="color:#888; font-size:13px; margin:4px 0;">{escape(s.get("empty_text") or "Không có gì mới.")}</p>'
        note = " · ".join(x for x in (s.get("note"), f"Cập nhật {s['as_of']}" if s.get("as_of") else None) if x)
        parts.append(email_section(title, inner, note or None))
        text += [s["title"].upper()] + [f"  {line}" for line in s.get("text", [])] + [""]

    now = datetime.now(TZ)
    dashboard = os.environ.get("DASHBOARD_URL") or f"https://{OWNER}.github.io/emailer-dashboard/"
    html = f"""\
<html><head><meta charset="utf-8"></head><body style="margin:0; padding:20px; background:#F6F6F7; font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:640px; margin:0 auto;">
<h1 style="font-size:20px; color:#17181A; margin:0 0 4px;">Tổng hợp buổi sáng</h1>
<div style="font-size:13px; color:#6E7178;">{now.strftime('%d/%m/%Y')}</div>
{''.join(parts)}
<p style="font-size:12px; color:#888;">Xem biểu đồ: <a href="{escape(dashboard)}">{escape(dashboard)}</a> ·
<a href="{escape(dashboard)}prices.html">Giá hôm nay</a></p>
</div></body></html>"""
    subject = f"Tổng hợp buổi sáng - {now.strftime('%d/%m/%Y')}"
    return subject, html, "\n".join([subject, ""] + text + [f"Biểu đồ: {dashboard}"])


def cmd_send():
    sender = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("SUMMARY_RECIPIENT")
    missing = [n for n, v in [("GMAIL_ADDRESS", sender), ("GMAIL_APP_PASSWORD", app_password),
                              ("SUMMARY_RECIPIENT", recipient)] if not v]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    with open(SUMMARY_FILE, encoding="utf-8") as f:
        summary = json.load(f)
    subject, html, text = build_email(summary)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
        server.login(sender, app_password)
        server.send_message(msg)
    print(f"Sent to {recipient}!")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("collect", "send", "preview", "sources"):
        print("Usage: python daily_summary.py [collect|send|preview|sources]", file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] == "sources":
        for name, reg in SOURCES.items():
            doc = (reg["fn"].__doc__ or "").strip().splitlines()
            print(f"{name:12} {reg['title']}" + (f"  — {doc[0]}" if doc else ""))
    elif sys.argv[1] == "collect":
        cmd_collect()
    elif sys.argv[1] == "send":
        cmd_send()
    else:  # write the email to email_preview.html without sending
        with open(SUMMARY_FILE, encoding="utf-8") as f:
            _, html, _ = build_email(json.load(f))
        with open("email_preview.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Wrote email_preview.html")


if __name__ == "__main__":
    main()
