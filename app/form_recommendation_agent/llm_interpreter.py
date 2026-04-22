from __future__ import annotations

from typing import Literal, TypedDict

from app.resume_form_mapper import is_forbidden_position_title, is_resume_section_title_line, is_valid_role_candidate


Confidence = Literal["high", "medium", "low"]


class LlmRoleResult(TypedDict):
    role: str
    confidence: Confidence
    reason: str


def _top_lines(resume_text: str, limit: int = 20) -> list[str]:
    return [ln.strip() for ln in (resume_text or "").splitlines()[:limit] if ln.strip()]


def infer_role_with_llm(resume_text: str) -> LlmRoleResult:
    """
    Заглушка "LLM-интерпретатора": берёт первые 20 строк и выбирает первую строку,
    похожую на роль. В будущем можно заменить реальным LLM без изменения интерфейса.
    """
    for line in _top_lines(resume_text, 20):
        low = line.lower().strip()
        if not low:
            continue
        if "professional summary" in low:
            continue
        if is_resume_section_title_line(low) or is_forbidden_position_title(line):
            continue
        if not is_valid_role_candidate(line):
            continue
        return {
            "role": line.strip(),
            "confidence": "medium",
            "reason": "извлечено из верхних строк резюме",
        }

    return {
        "role": "",
        "confidence": "low",
        "reason": "роль не найдена в верхней части резюме",
    }

