"""Run: python -m unittest discover tests

The sources read files from GitHub; here fetch_file is replaced by sample
files so the tests run offline.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import daily_summary  # noqa: E402
import summary_core  # noqa: E402
import summary_sources  # noqa: E402

today = date.today()
d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731

FILES = {
    ("gold-price-emailer", "state/price_history.json"): json.dumps({
        # Stored in thousands of đồng, as gold-price-emailer does.
        d(2): {"gold": {"table_0": {"SJC 1L": 119_000, "Nhẫn 9999": 114_500}}},
        d(1): {"gold": {"table_0": {"SJC 1L": 120_000, "Nhẫn 9999": 115_000}}},
        d(0): {"gold": {}}}),  # the last run of today failed to parse the table
    ("currency-rate-emailer", "rate_history.csv"):
        "timestamp,currency,rate\n"
        f"{d(1)} 08:00,USD,26000\n{d(1)} 08:00,EUR,30000\n{d(0)} 09:00,USD,26260\n{d(0)} 09:00,EUR,29700\n",
    ("vn-stock-price-emailer", "price_history.csv"):
        f"timestamp,ticker,close\n{d(1)} 15:00,VIC,100\n{d(0)} 15:00,VIC,110\n{d(0)} 15:00,FPT,90\n",
    ("interest-rate-emailer", "last_rates.json"): json.dumps({
        "central_banks": {"SBV": {"policy": "4.50%"}},
        "commercial_banks": {"A": [{"term": "12 tháng", "online": "5,9", "counter": "5,5"}],
                             "B": [{"term": "12M", "online": "6.3%", "counter": "6"}]}}),
    ("tech-price-mailer", "docs/price_history_latest.csv"):
        "Retailer,Category,Item,Price (VND),7 ngày change,Product URL\n"
        "X,SSD,SSD 1TB,1.990.000,-12%,https://x.vn/ssd\nX,RAM,RAM 16GB,990.000,+5%,https://x.vn/ram\nX,RAM,RAM 8GB,500.000,,\n",
    ("phone-tablet-price-emailer", "docs/models.json"): json.dumps({"updated_at": "2026-10-07T01:00:00+00:00", "models": [
        {"key": "a", "model": "Apple iPhone 16 128GB", "category": "phone",
         "offers": [{"shop": "t", "shop_name": "Tiki", "price": 19_000_000, "url": "https://tiki.vn/x"},
                    {"shop": "c", "shop_name": "CellphoneS", "price": 19_500_000}],
         "history": [[d(10), 20_000_000, "t"], [d(0), 19_000_000, "t"]]},
        {"key": "b", "model": "Only One Shop 64GB", "category": "phone",
         "offers": [{"shop": "t", "shop_name": "Tiki", "price": 3_000_000}], "history": []}]}),
}


def fake_fetch(repo, path, ref="main", owner=None):
    return FILES.get((repo, path))


def _run(name, path, conclusion, at="2026-10-09T01:00:00Z"):
    return {"name": name, "path": f".github/workflows/{path}", "status": "completed", "conclusion": conclusion,
            "created_at": at, "html_url": f"https://github.com/o/r/actions/runs/{abs(hash((name, at)))}"}


RUNS = {
    "currency-rate-emailer": [_run("Send Currency Rate Summary", "send-currency-rate.yml", "failure", "2026-10-09T07:09:07Z"),
                              _run("Send Currency Rate Summary", "send-currency-rate.yml", "failure")],
    "phone-tablet-price-emailer": [_run("Deploy Pages", "pages.yml", "failure"),
                                   _run("Send phone & tablet prices", "send-phone-prices.yml", "success")],
    "gold-price-emailer": [],  # Actions not enabled: never runs
}


with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as _f:
    WORKFLOWS = {r["name"]: r["workflow"] for r in json.load(_f)["repos"]}


def fake_runs(repo, since, owner=None):
    if repo == "broken-repo":
        raise RuntimeError("HTTP 403")
    return RUNS.get(repo, [_run("Main", WORKFLOWS[repo], "success")])


class Sources(unittest.TestCase):
    def setUp(self):
        self._orig = summary_sources.fetch_file
        summary_sources.fetch_file = fake_fetch

    def tearDown(self):
        summary_sources.fetch_file = self._orig

    def run_source(self, name, **opt):
        return summary_core.SOURCES[name]["fn"](opt)

    def test_every_block_is_well_formed(self):
        for name in daily_summary.DEFAULT_SOURCES:
            s = self.run_source(name)
            self.assertTrue(s["ok"], name)
            for b in s["blocks"]:
                self.assertIn(b["type"], ("chart", "tiles", "table"), name)
                if b["type"] == "table":
                    for r in b["rows"]:
                        self.assertEqual(len(r), len(b["columns"]), name)

    def test_values(self):
        gold = self.run_source("gold")
        self.assertEqual(gold["blocks"][1]["rows"][0], ["SJC 1L", 120_000_000, 0.84])
        cur = self.run_source("currency")["blocks"][0]["items"]
        self.assertEqual([(i["label"], i["change_pct"]) for i in cur], [("USD", 1.0), ("EUR", -1.0)])
        rates = self.run_source("interest")["blocks"][0]["rows"]
        self.assertEqual([r[0] for r in rates], ["B", "A"])  # highest online rate first
        tech = self.run_source("tech")["blocks"]
        self.assertEqual(tech[0]["rows"][0][0], ["SSD 1TB", "https://x.vn/ssd"])
        phones = self.run_source("phones")["blocks"][0]["rows"]
        self.assertEqual(len(phones), 1)  # models in one shop only are left out
        self.assertEqual(phones[0][1:], [19_000_000, "Tiki", 2, -5.0])

    def test_missing_data_is_not_an_error(self):
        summary_sources.fetch_file = lambda *a, **k: None
        for name in daily_summary.DEFAULT_SOURCES:
            self.assertFalse(self.run_source(name)["ok"], name)

    def test_health_lists_failing_bots_first(self):
        orig = summary_sources.fetch_runs
        summary_sources.fetch_runs = fake_runs
        try:
            s = self.run_source("health")
        finally:
            summary_sources.fetch_runs = orig
        rows = s["blocks"][0]["rows"]
        names = [r[0][0] for r in rows]
        # failures first (in config order), then bots that never ran, then healthy ones
        self.assertEqual(names[:3], ["phone-tablet-price-emailer", "currency-rate-emailer", "gold-price-emailer"])
        cur = rows[names.index("currency-rate-emailer")]
        self.assertEqual(cur[1:3], [2, 2])
        self.assertIn("14:09 09/10", cur[3])  # 07:09 UTC in Vietnam time
        self.assertTrue(cur[0][1].startswith("https://github.com/"))
        self.assertIn("Deploy Pages", rows[names.index("phone-tablet-price-emailer")][3])  # side workflows count too
        self.assertIn("không chạy", rows[names.index("gold-price-emailer")][3])
        self.assertTrue(all("bình thường" in r[3] for r in rows[3:]))
        self.assertTrue(s["note"].startswith("3 bot"))

    def test_health_survives_an_unreadable_repo(self):
        orig = summary_sources.fetch_runs
        summary_sources.fetch_runs = lambda repo, since, owner=None: fake_runs("broken-repo", since)
        try:
            s = self.run_source("health")
        finally:
            summary_sources.fetch_runs = orig
        self.assertFalse(s["ok"])  # nothing readable at all
        self.assertIn("không đọc được", s["blocks"][0]["rows"][0][3])

    def test_csv_history_needs_no_code(self):
        s = self.run_source("csv_history", repo="vn-stock-price-emailer", path="price_history.csv",
                            key_col="ticker", value_col="close", keys=["FPT"])
        self.assertEqual([i["label"] for i in s["blocks"][0]["items"]], ["FPT"])

    def test_price_adjustment_is_not_a_mover(self):
        # HDB's bonus shares: the bot stored 28000 then 28000/1.3 overnight, a -20%
        # "move" that no exchange allows in a day (UPCoM, the widest band, is ±15%).
        stocks = ("timestamp,ticker,close\n"
                  f"{d(1)} 09:00,HDB,27950\n{d(1)} 09:00,VIC,100\n{d(1)} 09:00,FPT,90\n"
                  f"{d(1)} 15:06,HDB,28000\n{d(0)} 07:53,HDB,21538.46156\n"
                  f"{d(0)} 15:00,HDB,22400\n{d(0)} 15:00,VIC,105\n{d(0)} 15:00,FPT,99\n")
        summary_sources.fetch_file = lambda repo, path, **k: stocks
        s = self.run_source("stocks")
        movers = s["blocks"][1]["rows"]
        self.assertEqual([m[0] for m in movers], ["FPT", "VIC"])
        hdb = s["blocks"][0]["items"][0]
        self.assertEqual((hdb["label"], hdb["change_pct"], hdb["note"]), ("HDB", None, "điều chỉnh giá"))
        self.assertIn("HDB", s["note"])
        self.assertEqual(s["text"][0], "HDB: 22,400.0 (điều chỉnh giá)")
        _, html, text = daily_summary.build_email({"sections": [{"id": "stocks", "title": "Chứng khoán", **s}]})
        self.assertNotIn("-19.", html + text)
        self.assertIn("điều chỉnh giá", html)

    def test_text_shows_a_dash_when_there_is_no_change_yet(self):
        summary_sources.fetch_file = lambda repo, path, **k: "timestamp,currency,rate\n" f"{d(0)} 09:00,USD,25641.03\n"
        s = self.run_source("currency")
        self.assertEqual(s["text"], ["USD: 25,641.03 (—)"])
        _, _, text = daily_summary.build_email({"sections": [{"id": "currency", "title": "Tỷ giá", **s}]})
        self.assertNotIn("None", text)
        summary_sources.fetch_file = fake_fetch
        self.assertEqual(self.run_source("currency")["text"][0], "USD: 26,260.0 (+1.0%)")


class ConfigAndEmail(unittest.TestCase):
    def test_config_entries(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"summary_sources": ["gold", "nope",
                                           {"source": "csv_history", "id": "fx2", "title": "Tỷ giá 2", "repo": "r"}]}, f)
        try:
            entries = daily_summary.load_source_config(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual([(e["id"], e["source"]) for e in entries], [("gold", "gold"), ("fx2", "csv_history")])
        self.assertEqual(entries[1]["title"], "Tỷ giá 2")
        self.assertEqual(entries[1]["options"], {"repo": "r"})

    def test_repo_config_is_valid(self):
        entries = daily_summary.load_source_config(os.path.join(ROOT, "config.json"))
        self.assertEqual([e["id"] for e in entries], ["health"] + daily_summary.DEFAULT_SOURCES)

    def test_email_renders_every_block(self):
        orig, orig_runs = summary_sources.fetch_file, summary_sources.fetch_runs
        summary_sources.fetch_file, summary_sources.fetch_runs = fake_fetch, fake_runs
        try:
            sections = [daily_summary.run_source({**e, "fn": summary_core.SOURCES[e["source"]]["fn"]})
                        for e in daily_summary.load_source_config(os.path.join(ROOT, "config.json"))]
        finally:
            summary_sources.fetch_file, summary_sources.fetch_runs = orig, orig_runs
        sections.append({"id": "x", "title": "Broken", "ok": False, "reason": "lỗi: boom"})
        subject, html, text = daily_summary.build_email({"sections": sections})
        self.assertIn("Tổng hợp buổi sáng", subject)
        for needle in ("Tình trạng các bot", "currency-rate-emailer", "Giá vàng", "120.000.000", "USD", "https://x.vn/ssd", "Apple iPhone 16 128GB", "lỗi: boom"):
            self.assertIn(needle, html)
        self.assertIn("GIÁ VÀNG", text)


if __name__ == "__main__":
    unittest.main()
