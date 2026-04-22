from __future__ import annotations
 
from dataclasses import asdict, dataclass
from typing import Any
 
from app.form_recommendation_agent import FormRecommendationAgent
 
 
@dataclass
class ResumeAgentProfile:
    primary_role: str
    alternate_roles: list[str]
    primary_industry: str
    adjacent_contexts: list[str]
    recommended_form_fields: dict[str, Any]
    clarification_question: str
    reasoning: str
    confidence: float
 
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
 
 
def _confidence_to_score(value: str) -> float:
    normalized = (value or "").strip().lower()
    if normalized == "high":
        return 0.85
    if normalized == "medium":
        return 0.62
    return 0.35
 
 
def _build_reasoning_from_recommendation(recommendation: dict[str, Any]) -> str:
    explanations = recommendation.get("explanations") or {}
    parts: list[str] = []
 
    for field_name in ["position", "industry", "location", "query_text", "keywords"]:
        text = str(explanations.get(field_name) or "").strip()
        if text:
            parts.append(text)
 
    clarification = str(recommendation.get("clarification_question") or "").strip()
    if clarification:
        parts.append(f"Уточнение: {clarification}")
 
    return " | ".join(parts)
 
 
def build_resume_agent_profile(
    resume_text: str,
    current_form_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_form_data = current_form_data or {}
 
    recommendation = FormRecommendationAgent().recommend(
        resume_text=resume_text or "",
        user_form_data=current_form_data,
    ).to_dict()
 
    confidence_map = recommendation.get("confidence_map") or {}
    confidence_values = [
        _confidence_to_score(confidence_map.get(field_name, "low"))
        for field_name in ["position", "industry", "location", "keywords", "email"]
    ]
    confidence = round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.35
 
    work_format = recommendation.get("work_format") or ""
    recommended_form_fields = {
        "position": recommendation.get("position") or "",
        # UI field `query_text` in job_search_form.html is the industry selector.
        # Keep the search-string in recommendation_payload; map UI to industry.
        "query_text": recommendation.get("industry") or "",
        "industry": recommendation.get("industry") or "",
        "keywords": ", ".join(recommendation.get("keywords") or []),
        "location": recommendation.get("location") or "",
        "email": recommendation.get("email") or "",
        "salary_min": recommendation.get("salary_min") or "",
        "employment_type": recommendation.get("employment_type") or "",
        "work_format": work_format,
        "remote": work_format == "remote",
    }
 
    extracted_facts = recommendation.get("extracted_facts") or {}
    profile = ResumeAgentProfile(
        primary_role=(recommendation.get("primary_role") or recommendation.get("position") or ""),
        alternate_roles=list(recommendation.get("alternative_roles") or []),
        primary_industry=recommendation.get("industry") or "",
        adjacent_contexts=list(extracted_facts.get("industry_candidates") or [])[1:3],
        recommended_form_fields=recommended_form_fields,
        clarification_question=recommendation.get("clarification_question") or "",
        reasoning=_build_reasoning_from_recommendation(recommendation),
        confidence=confidence,
    )
 
    result = profile.to_dict()
    result["recommendation_payload"] = recommendation
    return result
