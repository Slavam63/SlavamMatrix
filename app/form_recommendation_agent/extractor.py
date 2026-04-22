from __future__ import annotations

from app.resume_form_mapper import extract_raw_facts, normalize_facts, validate_facts

from .llm_interpreter import infer_role_with_llm
from .schemas import ResumeFacts


class ResumeFactExtractor:
    def extract(self, resume_text: str) -> ResumeFacts:
        raw = extract_raw_facts(resume_text or "")

        # LLM interceptor: после extract_raw_facts, до normalize_facts.
        llm_result = infer_role_with_llm(resume_text or "")
        if not (raw.get("position_raw") or "").strip() and (llm_result.get("role") or "").strip():
            raw["position_raw"] = str(llm_result["role"]).strip()
            raw["position_source_raw"] = "llm"

        normalized = normalize_facts(raw)
        validated = validate_facts(normalized)
        return self.resume_facts_from_pipeline(validated)

    def resume_facts_from_pipeline(self, validated: dict) -> ResumeFacts:
        return ResumeFacts(
            email=(validated.get("email") or "").strip().lower(),
            phone=(validated.get("phone") or "").strip(),
            location=(validated.get("location") or "").strip(),
            desired_position=(validated.get("position") or "").strip(),
            position_source=(validated.get("position_source") or "").strip(),
            past_roles=list(validated.get("past_roles") or []),
            competencies=list(validated.get("keywords") or []),
            primary_industry=(validated.get("primary_industry") or validated.get("industry") or "").strip(),
            industry_candidates=[],
            employment_type=(validated.get("employment_type") or "").strip(),
            work_format=(validated.get("work_format") or "").strip(),
            salary_min=validated.get("salary_min"),
        )

