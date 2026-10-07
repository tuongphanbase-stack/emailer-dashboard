#!/usr/bin/env python3
"""
Daily summary: collect the latest data from every emailer repo into one file,
and email a single morning digest.

    python daily_summary.py collect
        -> reads each emailer's saved state/history from GitHub and writes
           data/summary.json (also used by the charts in index.html)

    python daily_summary.py send
        -> builds the summary email from data/summary.json and sends it

Sources (each section degrades gracefully if its data isn't there yet):
  gold      gold-price-emailer          state/price_history.json  (branch gold-price-state)
  currency  currency-rate-emailer       rate_history.csv          (main)
  stocks    vn-stock-price-emailer      price_history.csv         (main)
  interest  interest-rate-emailer       last_rates.json           (branch interest-rate-state)
  tech      tech-price-mailer           docs/price_history_latest.csv (main)

Environment:
  GITHUB_OWNER        owner of the emailer repos (default: tuongphanbase-stack)
  GH_READ_TOKEN       optional; a token that can read the emailer repos. Needed
                      once those repos are private (public repos need none).
  GMAIL_ADDRESS, GMAIL_APP_PASSWORD, SUMMARY_RECIPIENT   for `send`
  DASHBOARD_URL       optional link at the bottom of the email
  TIMEZONE            optional, default Asia/Ho_Chi_Minh
"""

import csv
import io
import json
import os
import re
import smtplib
import ssl
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from zoneinfo import ZoneInfo

import requests

OWNER = os.environ.get("GITHUB_OWNER") or "tuongphanbase-stack"
TOKEN = os.environ.get("GH_READ_TOKEN") or ""
TZ = ZoneInfo(os.environ.get("TIMEZONE") or "Asia/Ho_Chi_Minh")
SUMMARY_FILE = os.path.join("data", "summary.json")
HISTORY_DAYS = 90           # how much history the charts get
CURRENCY_CODES = 8          # how many currencies to show
STOCK_TICKERS = 8           # how many stocks to show (in watchlist order)
GOLD_SERIES = 3             # how many gold products to chart


# --- Fetching -----------------------------------------------------------------

def fetch_file(repo, path, ref="main"):
    """Return a file's text from GitHub, or None if it doesn't exist."""
    if TOKEN:
        url = f"https://api.github.com/repos/{OWNER}/{repo}/contents/{path}"
        headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw+json"}
        resp = requests.get(url, headers=headers, params={"ref": ref}, timeout=30)
    else:
        url = f"https://raw.githubusercontent.com/{OWNER}/{repo}/{ref}/{path}"
        resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


def daily_last(points):
    """[(datetime, value), ...] -> [("YYYY-MM-DD", value), ...], last value per
    day, oldest first, limited to HISTORY_DAYS."""
    by_day = OrderedDict()
    for ts, value in sorted(points):
        by_day[ts.strftime("%Y-%m-%d")] = value
    return [[d, v] for d, v in list(by_day.items())[-HISTORY_DAYS:]]


def pct_change(points, hours=24):
    """% change from the value ~`hours` before the latest point to the latest."""
    if len(points) < 2:
        return None
    latest_ts, latest = points[-1]
    target = latest_ts - timedelta(hours=hours)
    earlier = [v for ts, v in points if ts <= target]
    base = earlier[-1] if earlier else None
    if not base:
        return None
    return round((latest - base) / base * 100, 2)


def parse_history_csv(text, key_col, value_col):
    """CSV with timestamp,<key>,<value> rows -> {key: [(datetime, float), ...]}"""
    series = OrderedDict()
    for row in csv.DictReader(io.StringIO(text)):
        try:
            ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M")
            series.setdefault(row[key_col], []).append((ts, float(row[value_col])))
        except (KeyError, ValueError):
            continue
    return series


# --- Sections -----------------------------------------------------------------

def collect_gold():
    text = fetch_file("gold-price-emailer", "state/price_history.json", ref="gold-price-state")
    if not text:
        return {"ok": False, "reason": "no gold price history yet"}
    history = json.loads(text)  # {date: {"gold": {table_i: {label: sell}}, "silver": {...}}}
    dates = sorted(history)
    latest_table = (history[dates[-1]].get("gold") or {}).get("table_0") or {}
    labels = list(latest_table)[:GOLD_SERIES]
    series = []
    for label in labels:
        pts = [[d, (history[d].get("gold") or {}).get("table_0", {}).get(label)] for d in dates]
        pts = [p for p in pts if p[1] is not None][-HISTORY_DAYS:]
        change = None
        if len(pts) >= 2 and pts[-2][1]:
            change = round((pts[-1][1] - pts[-2][1]) / pts[-2][1] * 100, 2)
        series.append({"name": label, "latest": pts[-1][1] if pts else None,
                       "change_pct": change, "points": pts})
    return {"ok": bool(series), "unit": "VND (sell)", "series": series,
            "as_of": dates[-1] if dates else None}


def collect_currency():
    text = fetch_file("currency-rate-emailer", "rate_history.csv")
    if not text:
        return {"ok": False, "reason": "no currency history yet"}
    series = parse_history_csv(text, "currency", "rate")
    items = []
    for code, pts in list(series.items())[:CURRENCY_CODES]:
        items.append({"code": code, "latest": round(pts[-1][1], 2), "change_pct": pct_change(pts),
                      "points": [[d, round(v, 2)] for d, v in daily_last(pts)]})
    as_of = max((pts[-1][0] for pts in series.values()), default=None)
    return {"ok": bool(items), "unit": "VND per unit", "items": items,
            "as_of": as_of.strftime("%Y-%m-%d %H:%M") if as_of else None}


def collect_stocks():
    text = fetch_file("vn-stock-price-emailer", "price_history.csv")
    if not text:
        return {"ok": False, "reason": "no stock history yet"}
    series = parse_history_csv(text, "ticker", "close")
    items = []
    for ticker, pts in list(series.items())[:STOCK_TICKERS]:
        items.append({"ticker": ticker, "latest": pts[-1][1], "change_pct": pct_change(pts),
                      "points": daily_last(pts)})
    # Biggest movers across the whole watchlist, by 24h change
    movers = []
    for ticker, pts in series.items():
        c = pct_change(pts)
        if c is not None:
            movers.append({"ticker": ticker, "latest": pts[-1][1], "change_pct": c})
    movers.sort(key=lambda m: abs(m["change_pct"]), reverse=True)
    as_of = max((pts[-1][0] for pts in series.values()), default=None)
    return {"ok": bool(items), "unit": "VND", "items": items, "movers": movers[:5],
            "as_of": as_of.strftime("%Y-%m-%d %H:%M") if as_of else None}


# "12 months", "12M", "12 Tháng", "12 tháng", "012 tháng"... - each bank labels it differently
TWELVE_MONTHS = re.compile(r"^0*12\s*(m|months?|th[aá]ng)$", re.IGNORECASE)


def collect_interest():
    text = fetch_file("interest-rate-emailer", "last_rates.json", ref="interest-rate-state")
    if not text:
        return {"ok": False, "reason": "no interest rate data yet"}
    data = json.loads(text)
    central = [{"name": name, "policy": v.get("policy"), "deposit": v.get("deposit")}
               for name, v in (data.get("central_banks") or {}).items()]
    banks = []
    for bank, terms in (data.get("commercial_banks") or {}).items():
        for t in terms or []:
            if TWELVE_MONTHS.match(str(t.get("term", "")).strip()):
                banks.append({"bank": bank, "online": t.get("online"), "counter": t.get("counter")})
                break

    def rate_value(s):
        try:
            return float(str(s).strip().rstrip("%").replace(",", "."))
        except ValueError:
            return -1
    banks.sort(key=lambda b: rate_value(b["online"]), reverse=True)
    return {"ok": bool(central or banks), "central_banks": central, "banks_12m": banks}


def collect_tech():
    text = fetch_file("tech-price-mailer", "docs/price_history_latest.csv")
    if not text:
        return {"ok": False, "reason": "no tech price data yet"}
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        change = (r.get("7 ngày change") or "").strip().rstrip("%")
        try:
            change = float(change.replace("+", ""))
        except ValueError:
            continue
        if change == 0:
            continue
        rows.append({"item": r.get("Item", ""), "category": r.get("Category", ""),
                     "price": r.get("Price (VND)", ""), "change_7d": change,
                     "url": r.get("Product URL", "")})
    drops = sorted([r for r in rows if r["change_7d"] < 0], key=lambda r: r["change_7d"])[:5]
    rises = sorted([r for r in rows if r["change_7d"] > 0], key=lambda r: -r["change_7d"])[:5]
    return {"ok": True, "drops": drops, "rises": rises}


SECTIONS = [("gold", collect_gold), ("currency", collect_currency), ("stocks", collect_stocks),
            ("interest", collect_interest), ("tech", collect_tech)]


def cmd_collect():
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "owner": OWNER}
    for key, fn in SECTIONS:
        try:
            summary[key] = fn()
        except Exception as e:  # one broken source must not sink the others
            summary[key] = {"ok": False, "reason": f"error: {e}"}
        status = "ok" if summary[key].get("ok") else summary[key].get("reason")
        print(f"  {key}: {status}")
    os.makedirs(os.path.dirname(SUMMARY_FILE), exist_ok=True)
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"Wrote {SUMMARY_FILE}")


# --- Email --------------------------------------------------------------------

def fmt_num(v, decimals=0):
    if v is None:
        return "—"
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")  # Vietnamese style 1.234.567,89


def fmt_change(pct):
    if pct is None:
        return '<span style="color:#888;">—</span>'
    if pct > 0:
        return f'<span style="color:#1E8A4C;">&#9650; {pct:+.2f}%</span>'
    if pct < 0:
        return f'<span style="color:#C13C30;">&#9660; {pct:+.2f}%</span>'
    return '<span style="color:#888;">0,00%</span>'


TH = 'style="text-align:left; padding:6px 8px; font-size:12px; color:#6E7178; font-weight:600; border-bottom:1px solid #E1E1E4;"'
THR = TH.replace('text-align:left;', 'text-align:right;')
TD = 'style="padding:6px 8px; font-size:14px; color:#17181A; border-bottom:1px solid #F0F0F2;"'
TDR = 'style="padding:6px 8px; font-size:14px; color:#17181A; border-bottom:1px solid #F0F0F2; text-align:right; white-space:nowrap;"'


def table(headers, rows, right_cols=()):
    head = "".join(f"<th {THR if i in right_cols else TH}>{escape(h)}</th>" for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f"<td {TDR if i in right_cols else TD}>{c}</td>" for i, c in enumerate(r)) + "</tr>"
        for r in rows)
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse; margin:6px 0 4px;"><tr>{head}</tr>{body}</table>')


def section(title, inner, note=None):
    note_html = f'<div style="font-size:12px; color:#888; margin-top:4px;">{escape(note)}</div>' if note else ""
    return (f'<div style="background:#fff; border:1px solid #E1E1E4; border-radius:12px; padding:16px; margin:12px 0;">'
            f'<h2 style="margin:0 0 6px; font-size:16px; color:#17181A;">{title}</h2>{inner}{note_html}</div>')


def unavailable(s):
    return f'<p style="color:#888; font-size:13px; margin:4px 0;">Chưa có dữ liệu ({escape(s.get("reason", "?"))}).</p>'


def build_email(summary):
    parts, text = [], []

    g = summary.get("gold", {})
    if g.get("ok"):
        rows = [[escape(s["name"]), fmt_num(s["latest"]), fmt_change(s["change_pct"])] for s in g["series"]]
        parts.append(section("&#129689; Giá vàng", table(["Sản phẩm", "Giá bán (VND)", "So với hôm trước"], rows, (1, 2)),
                             f"Cập nhật {g.get('as_of')}"))
        text += ["GIÁ VÀNG"] + [f"  {s['name']}: {fmt_num(s['latest'])} VND" for s in g["series"]]
    else:
        parts.append(section("&#129689; Giá vàng", unavailable(g)))

    c = summary.get("currency", {})
    if c.get("ok"):
        rows = [[escape(i["code"]), fmt_num(i["latest"], 2 if i["latest"] < 100 else 0), fmt_change(i["change_pct"])]
                for i in c["items"]]
        parts.append(section("&#128177; Tỷ giá", table(["Ngoại tệ", "VND / 1 đơn vị", "24 giờ"], rows, (1, 2)),
                             f"Tỷ giá thị trường, cập nhật {c.get('as_of')}"))
        text += ["TỶ GIÁ"] + [f"  {i['code']}: {fmt_num(i['latest'], 2)} VND" for i in c["items"]]
    else:
        parts.append(section("&#128177; Tỷ giá", unavailable(c)))

    s = summary.get("stocks", {})
    if s.get("ok"):
        rows = [[escape(i["ticker"]), fmt_num(i["latest"]), fmt_change(i["change_pct"])] for i in s["items"]]
        inner = table(["Mã", "Giá (VND)", "24 giờ"], rows, (1, 2))
        if s.get("movers"):
            inner += '<div style="font-size:13px; color:#6E7178; margin-top:10px;">Biến động mạnh nhất:</div>'
            inner += table(["Mã", "Giá (VND)", "24 giờ"],
                           [[escape(m["ticker"]), fmt_num(m["latest"]), fmt_change(m["change_pct"])] for m in s["movers"]],
                           (1, 2))
        parts.append(section("&#128200; Chứng khoán", inner, f"Cập nhật {s.get('as_of')}"))
        text += ["CHỨNG KHOÁN"] + [f"  {i['ticker']}: {fmt_num(i['latest'])} VND ({i['change_pct']}%)" for i in s["items"]]
    else:
        parts.append(section("&#128200; Chứng khoán", unavailable(s)))

    r = summary.get("interest", {})
    if r.get("ok"):
        inner = ""
        if r.get("banks_12m"):
            inner += table(["Ngân hàng", "Kỳ hạn 12 tháng (online)", "Tại quầy"],
                           [[escape(b["bank"]), escape(b["online"] or "—"), escape(b["counter"] or "—")]
                            for b in r["banks_12m"][:6]], (1, 2))
        if r.get("central_banks"):
            inner += table(["Ngân hàng trung ương", "Lãi suất điều hành"],
                           [[escape(b["name"]), escape(b["policy"] or "—")] for b in r["central_banks"]], (1,))
        parts.append(section("&#127974; Lãi suất", inner))
        text += ["LÃI SUẤT 12 THÁNG"] + [f"  {b['bank']}: {b['online']}" for b in r.get("banks_12m", [])[:6]]
    else:
        parts.append(section("&#127974; Lãi suất", unavailable(r)))

    t = summary.get("tech", {})
    if t.get("ok") and (t.get("drops") or t.get("rises")):
        def tech_rows(items):
            return [[f'<a href="{escape(i["url"])}" style="color:#17181A;">{escape(i["item"])}</a>',
                     escape(i["price"]), fmt_change(i["change_7d"])] for i in items]
        inner = ""
        if t.get("drops"):
            inner += '<div style="font-size:13px; color:#6E7178;">Giảm giá nhiều nhất (7 ngày):</div>'
            inner += table(["Sản phẩm", "Giá (VND)", "7 ngày"], tech_rows(t["drops"]), (1, 2))
        if t.get("rises"):
            inner += '<div style="font-size:13px; color:#6E7178; margin-top:10px;">Tăng giá nhiều nhất (7 ngày):</div>'
            inner += table(["Sản phẩm", "Giá (VND)", "7 ngày"], tech_rows(t["rises"]), (1, 2))
        parts.append(section("&#128187; Giá RAM / SSD / Laptop", inner))
        text += ["GIÁ RAM/SSD/LAPTOP (7 ngày)"] + [f"  {i['item']}: {i['price']} ({i['change_7d']:+}%)"
                                                  for i in t.get("drops", []) + t.get("rises", [])]
    elif t.get("ok"):
        parts.append(section("&#128187; Giá RAM / SSD / Laptop",
                             '<p style="color:#888; font-size:13px; margin:4px 0;">Không có thay đổi giá trong 7 ngày qua.</p>'))
    else:
        parts.append(section("&#128187; Giá RAM / SSD / Laptop", unavailable(t)))

    now = datetime.now(TZ)
    dashboard = os.environ.get("DASHBOARD_URL") or f"https://{OWNER}.github.io/emailer-dashboard/"
    html = f"""\
<html><head><meta charset="utf-8"></head><body style="margin:0; padding:20px; background:#F6F6F7; font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:640px; margin:0 auto;">
<h1 style="font-size:20px; color:#17181A; margin:0 0 4px;">Tổng hợp buổi sáng</h1>
<div style="font-size:13px; color:#6E7178;">{now.strftime('%d/%m/%Y')}</div>
{''.join(parts)}
<p style="font-size:12px; color:#888;">Xem biểu đồ: <a href="{escape(dashboard)}">{escape(dashboard)}</a></p>
</div></body></html>"""
    subject = f"Tổng hợp buổi sáng - {now.strftime('%d/%m/%Y')}"
    return subject, html, "\n".join([subject, ""] + text + ["", f"Biểu đồ: {dashboard}"])


def cmd_send():
    sender = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("SUMMARY_RECIPIENT")
    missing = [n for n, v in [("GMAIL_ADDRESS", sender), ("GMAIL_APP_PASSWORD", app_password),
                              ("SUMMARY_RECIPIENT", recipient)] if not v]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    with open(SUMMARY_FILE) as f:
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
    if len(sys.argv) != 2 or sys.argv[1] not in ("collect", "send", "preview"):
        print("Usage: python daily_summary.py [collect|send|preview]", file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] == "collect":
        cmd_collect()
    elif sys.argv[1] == "send":
        cmd_send()
    else:  # write the email to email_preview.html without sending
        with open(SUMMARY_FILE) as f:
            _, html, _ = build_email(json.load(f))
        with open("email_preview.html", "w") as f:
            f.write(html)
        print("Wrote email_preview.html")


if __name__ == "__main__":
    main()
