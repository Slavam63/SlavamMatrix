import unittest


from app.form_recommendation_agent import FormRecommendationAgent


class FormRecommendationAgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = FormRecommendationAgent()

    def test_role_priority_pipeline_headline_wins_llm_not_used(self):
        resume_text = """
        John Doe
        Finance Analyst / FP&A Specialist
        john@example.com
        Abu Dhabi
        """
        result = self.agent.recommend(resume_text).to_dict()
        self.assertEqual(result.get("position"), "Finance Analyst / FP&A Specialist")
        self.assertNotEqual(result.get("position_source"), "llm")
        self.assertFalse(bool(result.get("llm_used")))

    def test_llm_fallback_when_pipeline_headline_stops_on_section_title(self):
        resume_text = """
        John Doe
        Professional Summary
        Finance Analyst / FP&A Specialist
        john@example.com
        Abu Dhabi
        """
        result = self.agent.recommend(resume_text).to_dict()
        self.assertEqual(result.get("position"), "Finance Analyst / FP&A Specialist")
        self.assertEqual(result.get("position_source"), "llm")
        self.assertTrue(bool(result.get("llm_used")))

    def test_llm_ignores_professional_summary_title(self):
        resume_text = """
        Professional Summary
        Ten years in budgeting and forecasting.
        john@example.com
        Abu Dhabi
        """
        result = self.agent.recommend(resume_text).to_dict()
        self.assertNotEqual((result.get("position") or "").lower(), "professional summary")
        self.assertEqual((result.get("position") or "").strip(), "")
        self.assertFalse(bool(result.get("llm_used")))


if __name__ == "__main__":
    unittest.main()

