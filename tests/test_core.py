import os
import unittest

os.environ.setdefault("DEAL_MIN_RUB", "10000000")
os.environ.setdefault("DEAL_MAX_RUB", "90000000")
os.environ.setdefault("DEAL_MIN_ADVANCE_PCT", "20")
os.environ.setdefault("DEAL_BG_LIMIT_RUB", "17000000")
os.environ.setdefault("DEAL_KEYWORDS", "благоустройство,клининг,снег")
os.environ.setdefault("DEAL_EXCLUDE_KEYWORDS", "ремонт дорог")

from app import ingest


class CoreRegressionTests(unittest.TestCase):
    def test_price_and_advance_parsing(self):
        item = {
            "initialMaxPrice": 25000000,
            "purchaseNumber": "0114500000026000001",
            "name": "Благоустройство территории",
            "description": "Предусмотрен аванс 30%",
        }
        blob = ingest._text(item).lower()
        self.assertEqual(ingest._price(item), 25000000.0)
        self.assertEqual(ingest._advance(item, blob, 25000000.0), 30.0)

    def test_excluded_scope_is_rejected(self):
        item = {
            "initialMaxPrice": 30000000,
            "name": "Ремонт дорог",
            "description": "Ремонт дорог и содержание",
        }
        ok, reason = ingest._fit(item)
        self.assertFalse(ok)
        self.assertEqual(reason, "вне профиля")

    def test_refresh_dashboard_has_separate_source_and_review_states(self):
        with open("app/main.py", encoding="utf-8") as f:
            text = f.read()
        self.assertIn('"source_running"', text)
        self.assertIn('"review_running"', text)
        self.assertNotIn("\n}async function pollRefreshStatus()", text)


    def test_rss_region_gate(self):
        self.assertEqual(ingest._rss_region("Закупка в г. Магасе, Республика Ингушетия"), "Республика Ингушетия")
        self.assertEqual(ingest._rss_region("Работы в Ростове-на-Дону"), "Ростовская область")
        self.assertEqual(ingest._rss_region("Работы в Казани"), "")
    def test_render_search_depth(self):
        with open("render.yaml", encoding="utf-8") as f:
            text = f.read()
        self.assertIn('key: GOSPLAN_MAX_PAGES\n        value: "4"', text)
        self.assertIn('key: GOSPLAN_TEST_INTERVAL\n        value: "8"', text)
        self.assertNotIn("    disk:", text)
        self.assertIn('key: AUTO_REFRESH\n        value: "false"', text)


if __name__ == "__main__":
    unittest.main()
