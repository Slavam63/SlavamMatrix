import unittest


import importlib.util
from pathlib import Path


def _load_parser_module():
    # В проекте `app/__init__.py` зависит от web-слоя (routes), поэтому для юнит-тестов
    # грузим `app/parser.py` напрямую по пути.
    root = Path(__file__).resolve().parents[1]
    parser_path = root / "app" / "parser.py"
    spec = importlib.util.spec_from_file_location("matrix_parser_app_parser", parser_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


_PARSER = _load_parser_module()
finance_fpa_reject_reason = _PARSER.finance_fpa_reject_reason


class FinanceFpaRelevanceTests(unittest.TestCase):
    def _payload(self):
        return {
            "position": "Senior Finance Analyst / FP&A",
            "query_text": "Finance Analyst FP&A",
            "keywords": ["fp&a", "budgeting", "ifrs"],
            "agent_profile": {"seniority_level": "senior"},
            "diagnostics": {},
        }

    def test_bi_without_finance_reject(self):
        reason = finance_fpa_reject_reason(
            self._payload(),
            {"title": "BI Analyst (Power BI, Tableau)", "description": "Dashboards, data marts, SQL."},
        )
        self.assertEqual(reason, "finance_fpa_no_context")

    def test_business_analyst_without_finance_reject(self):
        reason = finance_fpa_reject_reason(
            self._payload(),
            {"title": "Business Analyst", "description": "Product metrics, roadmap, stakeholder management."},
        )
        self.assertEqual(reason, "finance_fpa_no_context")

    def test_business_analyst_with_ifrs_keep(self):
        reason = finance_fpa_reject_reason(
            self._payload(),
            {"title": "Business Analyst", "description": "IFRS reporting, budgeting and financial reporting."},
        )
        self.assertEqual(reason, "")

    def test_product_strategy_reject(self):
        reason = finance_fpa_reject_reason(
            self._payload(),
            {"title": "Product Strategy Manager", "description": "Roadmap, growth strategy, product vision."},
        )
        self.assertEqual(reason, "finance_fpa_negative_title")

    def test_financial_analyst_keep(self):
        reason = finance_fpa_reject_reason(
            self._payload(),
            {"title": "Financial Analyst (FP&A)", "description": "Budgeting, forecasting, P&L, IFRS."},
        )
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()

