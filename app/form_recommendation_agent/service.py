from __future__ import annotations

from typing import Any

from app.resume_form_mapper import infer_role_family, infer_seniority

from .extractor import ResumeFactExtractor
from .schemas import FormRecommendationResult


class FormRecommendationAgent:
    def __init__(self, extractor: ResumeFactExtractor | None = None):
        self.extractor = extractor or ResumeFactExtractor()

    def recommend(self, resume_text: str, user_form_data: dict[str, Any] | None = None) -> FormRecommendationResult:
        user_form_data = user_form_data or {}
        facts = self.extractor.extract(resume_text or "")

        manual_position = str(user_form_data.get("position") or "").strip()
        manual_location = str(user_form_data.get("location") or "").strip()
        manual_email = str(user_form_data.get("email") or "").strip().lower()
        manual_keywords = str(user_form_data.get("keywords") or "").strip()

        position = manual_position or facts.desired_position
        location = manual_location or facts.location
        email = manual_email or facts.email
        keywords = [k.strip() for k in manual_keywords.split(",") if k.strip()] if manual_keywords else list(facts.competencies)

        query_text = " ".join([p for p in [position, location] if p]).strip()

        seniority_level = infer_seniority(resume_text or "", [position] + list(facts.past_roles))
        role_family = infer_role_family(keywords, position)

        llm_used = (facts.position_source or "").strip().lower() == "llm" and not manual_position and bool(position)

        return FormRecommendationResult(
            position=position,
            query_text=query_text,
            query_text_variants=[],
            keywords=keywords[:12],
            industry=str(user_form_data.get("industry") or facts.primary_industry or "").strip(),
            location=location,
            email=email,
            employment_type=str(user_form_data.get("employment_type") or facts.employment_type or "").strip(),
            work_format=str(user_form_data.get("work_format") or facts.work_format or "").strip(),
            salary_min=(user_form_data.get("salary_min") if user_form_data.get("salary_min") not in ("", None) else facts.salary_min),
            primary_role=position,
            alternative_roles=[],
            clarification_question="",
            confidence_map={},
            explanations={},
            warnings=list(dict.fromkeys((user_form_data.get("warnings") or []) + [])) if isinstance(user_form_data.get("warnings"), list) else [],
            extracted_facts=facts,
            position_source=("user" if manual_position else (facts.position_source or "")),
            seniority_level=seniority_level,
            role_family=role_family,
            llm_used=llm_used,
        )

