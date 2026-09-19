"""Request validation for POST /api/castdev — allowlist q1–q4 only."""

from __future__ import annotations

from typing import Any

from . import config


ALLOWED = frozenset({"q1", "q2", "q3", "q4"})
# Optional non-research metadata for dedup only — never stored as profile.
OPTIONAL_META = frozenset({"submit_token", "dataset"})


class ValidationError(Exception):
    def __init__(self, message: str, code: str = "validation_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def validate_payload(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValidationError("Ожидается JSON-объект.", "invalid_json")

    extra = set(raw.keys()) - ALLOWED - OPTIONAL_META
    if extra:
        raise ValidationError(
            "Допустимы только поля q1, q2, q3, q4.",
            "extra_fields",
        )

    missing = [k for k in ("q1", "q2", "q3", "q4") if k not in raw]
    if missing:
        raise ValidationError("Не хватает обязательных полей.", "missing_fields")

    out: dict[str, str] = {}
    for key in ("q1", "q2", "q3", "q4"):
        val = raw[key]
        if not isinstance(val, str):
            raise ValidationError(f"Поле {key} должно быть строкой.", "invalid_type")
        trimmed = val.strip()
        if len(trimmed) < config.MIN_ANSWER_LEN:
            raise ValidationError("Пустые ответы не принимаются.", "empty_answer")
        if len(trimmed) > config.MAX_ANSWER_LEN:
            raise ValidationError("Слишком длинный ответ.", "too_long")
        out[key] = trimmed
    return out


def resolve_dataset(raw: dict) -> str:
    ds = raw.get("dataset", "production")
    if ds not in ("production", "test"):
        raise ValidationError("Некорректный dataset.", "invalid_dataset")
    # Public endpoint always production unless explicitly enabled for local QA
    return ds
