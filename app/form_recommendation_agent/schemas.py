from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ResumeFacts:
    email: str = ""
    phone: str = ""
    location: str = ""
    desired_position: str = ""
    past_roles: list[str] = field(default_factory=list)
    competencies: list[str] = field(default_factory=list)
    primary_industry: str = ""
    industry_candidates: list[str] = field(default_factory=list)
    employment_type: str = ""
    work_format: str = ""
    salary_min: int | None = None
    position_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FormRecommendationResult:
    position: str = ""
    query_text: str = ""
    query_text_variants: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    industry: str = ""
    location: str = ""
    email: str = ""
    employment_type: str = ""
    work_format: str = ""
    salary_min: int | None = None
    primary_role: str = ""
    alternative_roles: list[str] = field(default_factory=list)
    clarification_question: str = ""
    confidence_map: dict[str, str] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extracted_facts: ResumeFacts = field(default_factory=ResumeFacts)
    position_source: str = ""
    seniority_level: str = "unknown"
    role_family: str = "unknown"
    llm_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["extracted_facts"] = self.extracted_facts.to_dict()
        return data

