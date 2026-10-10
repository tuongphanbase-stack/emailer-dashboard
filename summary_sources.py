"""The summary's data sources. Each one reads an emailer repo's saved data
and returns a section made of generic blocks (see summary_core.py).

To add a source: write a function here with @source(...), then list its id
in config.json -> "summary_sources". A plain CSV history (time, key, value)
needs no code at all: use the "csv_history" source with options.
"""
import csv
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from summary_core import (HISTORY_DAYS, chart, col, daily_last, empty, fetch_file, fetch_runs,
                          parse_history_csv, pct_change, source, table, tiles)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LOCAL_TZ = ZoneInfo(os.environ.get("TIMEZONE") or "Asia/Ho_Chi_Minh")


def _local_time(iso):
    """GitHub's "2026-10-09T07:09:07Z" -> "14:09 09/10" in the email's timezone."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LOCAL_TZ).strftime("%H:%M %d/%m")
    except (AttributeError, ValueError):
        return "?"


@source("health", "Tình trạng các bot", icon="🩺")
def health(opt):
    """Every workflow run of the bots in config.json -> "repos" over the last
    `hours` (default 24): one row per repo, failing repos first. This replaces
    GitHub's one-email-per-failed-run notices with one line a day.
    Options: hours."""
    hours = int(opt.get("hours", 24))
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    owner = cfg.get("owner")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows, bad, errors = [], 0, []
    for repo in cfg.get("repos", []):
        name = repo["name"]
        try:
            runs = [r for r in fetch_runs(name, since, owner=owner) if r.get("status") == "completed"]
        except Exception as e:  # one repo the API refuses must not hide the rest
            errors.append(name)
            rows.append((2, [[name, f"https://github.com/{owner}/{name}/actions"], None, None, f"⚠️ không đọc được ({e})"]))
            continue
        failed = [r for r in runs if r.get("conclusion") in ("failure", "timed_out", "startup_failure")]
        main_runs = [r for r in runs if r.get("path", "").endswith("/" + repo.get("workflow", ""))]
        if failed:
            latest = failed[0]
            status = f"❌ {latest.get('name', '')} lỗi lúc {_local_time(latest.get('created_at'))}"
            link = latest.get("html_url") or f"https://github.com/{owner}/{name}/actions"
            rank = 0
            bad += 1
        elif not main_runs:
            status, link, rank = "⏸️ không chạy lần nào", f"https://github.com/{owner}/{name}/actions", 1
            bad += 1
        else:
            status, link, rank = "✅ bình thường", main_runs[0].get("html_url") or "", 3
        rows.append((rank, [[name, link], len(runs), len(failed), status]))
    rows = [r for _, r in sorted(rows, key=lambda x: x[0])]
    note = (f"{bad} bot cần xem lại" if bad else "Tất cả bot chạy bình thường") + f" · {hours} giờ qua"
    return {"ok": bool(rows) and len(errors) < len(rows), "note": note,
            "blocks": [table([col("Bot", "link"), col("Lượt chạy", "num"), col("Lỗi", "num"), col("Tình trạng")], rows)],
            "text": [f"{r[0][0]}: {r[3]} ({r[2] or 0}/{r[1] or 0} lỗi)" for r in rows]}


def _pct_text(pct, note=None):
    """A change for the plain-text email: "+1.5%", or the note / "—" when there is none."""
    return f"{pct:+}%" if pct is not None else (note or "—")


@source("csv_history", "Lịch sử", icon="📈")
def csv_history(opt):
    """Any CSV of time,key,value rows -> tiles with sparklines.
    Options: repo, path, ref, key_col, value_col, time_col, time_format, limit, unit, keys,
    movers, max_move_pct (a bigger 24h change is a price adjustment, not a real move)."""
    text = fetch_file(opt["repo"], opt["path"], ref=opt.get("ref", "main"))
    if not text:
        return empty(f"chưa có {opt['path']}")
    series = parse_history_csv(text, opt["key_col"], opt["value_col"], opt.get("time_col", "timestamp"),
                               opt.get("time_format", "%Y-%m-%d %H:%M"))
    keys = opt.get("keys") or list(series)
    keys = [k for k in keys if k in series][: int(opt.get("limit", 8))]
    digits = int(opt.get("decimals", 2))
    changes = {k: pct_change(p) for k, p in series.items()}
    # A change no trading day allows means the history holds a price adjustment
    # (bonus shares, split: 28000 -> 28000/1.3), so it is not shown as a move.
    max_move = opt.get("max_move_pct")
    adjusted = [k for k, c in changes.items() if c is not None and max_move is not None and abs(c) > float(max_move)]
    for k in adjusted:
        changes[k] = None
    items = [{"label": k, "value": round(series[k][-1][1], digits), "change_pct": changes[k],
              "period": "24h", "points": [[d, round(v, digits)] for d, v in daily_last(series[k])]} for k in keys]
    for i in items:
        if i["label"] in adjusted:
            i["note"] = "điều chỉnh giá"
    as_of = max((series[k][-1][0] for k in keys), default=None)
    out = {"ok": bool(items), "as_of": as_of.strftime("%Y-%m-%d %H:%M") if as_of else None,
           "blocks": [tiles(items, opt.get("unit", ""))],
           "text": [f"{i['label']}: {i['value']:,} ({_pct_text(i['change_pct'], i.get('note'))})" for i in items]}
    if adjusted:
        out["note"] = f"Giá đã điều chỉnh (chia, thưởng cổ phiếu), không tính biến động: {', '.join(adjusted)}"
    movers = sorted(((k, c, series[k][-1][1]) for k, c in changes.items() if c is not None),
                    key=lambda m: -abs(m[1]))[: int(opt.get("movers", 0))]
    if movers:
        out["blocks"].append(table([col("Mã"), col("Giá", "num"), col("24 giờ", "change")],
                                   [[k, v, c] for k, c, v in movers], caption="Biến động mạnh nhất"))
    return out


def _gold_vnd(value):
    """gold-price-emailer stores gold in thousands of đồng per lượng (143000 =
    143.000.000 đ); accept full đồng too, in case it is ever stored that way."""
    if value is None:
        return None
    return value * 1000 if value < 10_000_000 else value


@source("gold", "Giá vàng", icon="🪙")
def gold(opt):
    """Gold sell prices from gold-price-emailer's history. Options: owner (the
    GitHub account that runs the bot, if not GITHUB_OWNER), limit."""
    text = fetch_file("gold-price-emailer", "state/price_history.json", ref="gold-price-state",
                      owner=opt.get("owner"))
    if not text:
        return empty("chưa có lịch sử giá vàng")
    history = json.loads(text)  # {date: {"gold": {table_i: {label: sell, in nghìn đồng}}, ...}}
    dates = sorted(history)
    # The latest day can lack the table if that run failed to parse it; use the
    # most recent day that has it.
    latest = next(((history[d].get("gold") or {}).get("table_0") for d in reversed(dates)
                   if (history[d].get("gold") or {}).get("table_0")), {})
    series, rows = [], []
    for label in list(latest)[: int(opt.get("limit", 3))]:
        pts = [[d, _gold_vnd((history[d].get("gold") or {}).get("table_0", {}).get(label))] for d in dates]
        pts = [p for p in pts if p[1] is not None][-HISTORY_DAYS:]
        change = round((pts[-1][1] - pts[-2][1]) / pts[-2][1] * 100, 2) if len(pts) >= 2 and pts[-2][1] else None
        series.append({"name": label, "points": pts})
        rows.append([label, pts[-1][1] if pts else None, change])
    return {"ok": bool(series), "as_of": dates[-1], "note": "Giá bán, VND/lượng",
            "blocks": [chart(series, "VND"),
                       table([col("Sản phẩm"), col("Giá bán (VND)", "num"), col("So với hôm trước", "change")], rows)],
            "text": [f"{r[0]}: {r[1]:,.0f} VND" for r in rows if r[1]]}


@source("currency", "Tỷ giá", icon="💱")
def currency(opt):
    return csv_history({"repo": "currency-rate-emailer", "path": "rate_history.csv", "key_col": "currency",
                        "value_col": "rate", "unit": "VND", "limit": opt.get("limit", 8), **opt})


@source("stocks", "Chứng khoán", icon="📈")
def stocks(opt):
    return csv_history({"repo": "vn-stock-price-emailer", "path": "price_history.csv", "key_col": "ticker",
                        "value_col": "close", "unit": "VND", "decimals": 0, "limit": opt.get("limit", 8),
                        "movers": 5, "max_move_pct": 15, **opt})  # widest daily band: UPCoM ±15% (HNX ±10%, HOSE ±7%)


# "12 months", "12M", "12 Tháng", "012 tháng"... - each bank labels it differently
TWELVE_MONTHS = re.compile(r"^0*12\s*(m|months?|th[aá]ng)$", re.IGNORECASE)


def _rate(s):
    try:
        return float(str(s).strip().rstrip("%").replace(",", "."))
    except ValueError:
        return None


@source("interest", "Lãi suất", icon="🏦")
def interest(opt):
    text = fetch_file("interest-rate-emailer", "last_rates.json", ref="interest-rate-state")
    if not text:
        return empty("chưa có dữ liệu lãi suất")
    data = json.loads(text)
    banks = []
    for bank, terms in (data.get("commercial_banks") or {}).items():
        t = next((t for t in terms or [] if TWELVE_MONTHS.match(str(t.get("term", "")).strip())), None)
        if t:
            banks.append([bank, _rate(t.get("online")), _rate(t.get("counter"))])
    banks.sort(key=lambda b: b[1] if b[1] is not None else -1, reverse=True)
    central = [[name, v.get("policy")] for name, v in (data.get("central_banks") or {}).items()]
    blocks = []
    if banks:
        blocks.append(table([col("Ngân hàng"), col("12 tháng online (%)", "num"), col("Tại quầy (%)", "num")],
                            banks[: int(opt.get("limit", 8))], caption="Lãi suất tiết kiệm 12 tháng"))
    if central:
        blocks.append(table([col("Ngân hàng trung ương"), col("Lãi suất điều hành")], central))
    return {"ok": bool(blocks), "blocks": blocks, "text": [f"{b[0]}: {b[1]}%" for b in banks[:6]]}


@source("tech", "Giá RAM / SSD / Laptop", icon="💻")
def tech(opt):
    text = fetch_file("tech-price-mailer", "docs/price_history_latest.csv")
    if not text:
        return empty("chưa có dữ liệu giá linh kiện")
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            change = float((r.get("7 ngày change") or "").strip().rstrip("%").replace("+", ""))
        except ValueError:
            continue
        if change:
            rows.append([[r.get("Item", ""), r.get("Product URL", "")], r.get("Price (VND)", ""), change])
    n = int(opt.get("limit", 5))
    drops = sorted([r for r in rows if r[2] < 0], key=lambda r: r[2])[:n]
    rises = sorted([r for r in rows if r[2] > 0], key=lambda r: -r[2])[:n]
    cols = [col("Sản phẩm", "link"), col("Giá (VND)", "num"), col("7 ngày", "change")]
    blocks = [table(cols, x, caption=c) for x, c in ((drops, "Giảm giá nhiều nhất"), (rises, "Tăng giá nhiều nhất")) if x]
    return {"ok": True, "note": "Thay đổi giá trong 7 ngày", "blocks": blocks,
            "empty_text": None if blocks else "Không có thay đổi giá trong 7 ngày qua.",
            "text": [f"{r[0][0]}: {r[1]} ({r[2]:+}%)" for r in drops + rises]}


@source("phones", "Giá điện thoại & máy tính bảng", icon="📱")
def phones(opt):
    text = fetch_file("phone-tablet-price-emailer", "docs/models.json")
    if not text:
        return empty("chưa có dữ liệu giá điện thoại")
    data = json.loads(text)
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    rows = []
    for m in data.get("models", []):
        offers = m.get("offers") or []
        if len(offers) < 2:
            continue
        best = offers[0]
        before = [p for d, p, *_ in m.get("history", []) if d <= week_ago]
        change = round((best["price"] - before[-1]) * 100 / before[-1], 2) if before else None
        rows.append((len(offers), [[m["model"], best.get("url") or ""], best["price"], best["shop_name"], len(offers), change]))
    rows = [r for _, r in sorted(rows, key=lambda x: -x[0])][: int(opt.get("limit", 10))]
    return {"ok": bool(rows), "as_of": data.get("updated_at", "")[:16].replace("T", " "),
            "note": "Model bán ở nhiều cửa hàng nhất, giá rẻ nhất hiện tại",
            "blocks": [table([col("Model", "link"), col("Rẻ nhất (VND)", "num"), col("Cửa hàng"),
                              col("Số shop", "num"), col("7 ngày", "change")], rows)],
            "text": [f"{r[0][0]}: {r[1]:,} ({r[2]})" for r in rows]}
