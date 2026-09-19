"""Russian display labels for CASTDEV09.26 admin analytics (Tatiana-facing)."""

from __future__ import annotations

QUESTION_TITLES = {
    "q1": "Вопрос 1",
    "q2": "Вопрос 2",
    "q3": "Вопрос 3",
    "q4": "Вопрос 4",
    "cross": "Между вопросами",
}

QUESTION_PROMPTS_SHORT = {
    "q1": "как ищут работу",
    "q2": "критерии выбора позиции",
    "q3": "что происходит после нахождения возможности",
    "q4": "что меняли бы / оставляли",
}

DATASET_LABELS = {
    "production": "Боевые ответы",
    "test": "Тестовые",
}

STANCE_LABELS = {
    "positive_use": "позитивное использование",
    "negative_while_using": "негатив при использовании",
    "abandoned": "отказались от канала",
    "mentioned_neutral": "упоминание без оценки",
}

CRITERION_LABELS = {
    "role_content": "содержание роли",
    "level": "уровень позиции",
    "company": "компания / бренд",
    "compensation": "компенсация",
    "industry": "отрасль",
    "specific_vacancy": "конкретная вакансия",
}

FRICTION_LABELS = {
    "first_contact": "первый контакт",
    "interest_experience": "заинтересованность / опыт",
    "interview": "интервью",
    "terms": "условия / оффер",
    "other": "другое",
}

INTENT_LABELS = {
    "wants_change": "хотели бы изменить",
    "wants_keep": "оставили бы как есть",
}

CHANNEL_LABELS = {
    "hh": "HH",
    "linkedin": "LinkedIn",
    "recruiters": "рекрутеры",
    "network": "знакомства / сеть",
    "direct": "прямые обращения",
    "telegram": "Telegram",
}

# Feature columns shown in the per-question analytics matrix
Q1_FEATURE_COLUMNS = [
    ("channel_stance:hh", "positive_use", "HH · позитив"),
    ("channel_stance:hh", "negative_while_using", "HH · негатив"),
    ("channel_stance:hh", "abandoned", "HH · отказ"),
    ("channel_stance:hh", "mentioned_neutral", "HH · нейтрально"),
    ("channel_stance:linkedin", "positive_use", "LinkedIn · позитив"),
    ("channel_stance:linkedin", "negative_while_using", "LinkedIn · негатив"),
    ("channel_stance:linkedin", "abandoned", "LinkedIn · отказ"),
    ("channel_stance:network", "positive_use", "Сеть · позитив"),
    ("channel_stance:network", "abandoned", "Сеть · отказ"),
    ("channel_stance:recruiters", "positive_use", "Рекрутеры · позитив"),
    ("channel_stance:recruiters", "negative_while_using", "Рекрутеры · негатив"),
]

Q2_FEATURE_COLUMNS = [
    ("decision_criterion", k, CRITERION_LABELS[k]) for k in CRITERION_LABELS
]

Q3_FEATURE_COLUMNS = [
    ("friction", k, FRICTION_LABELS[k]) for k in FRICTION_LABELS
]

Q4_FEATURE_COLUMNS = [
    ("intent", k, INTENT_LABELS[k]) for k in INTENT_LABELS
]

FEATURE_COLUMNS_BY_QUESTION = {
    "q1": Q1_FEATURE_COLUMNS,
    "q2": Q2_FEATURE_COLUMNS,
    "q3": Q3_FEATURE_COLUMNS,
    "q4": Q4_FEATURE_COLUMNS,
}


def feature_value_ru(feature_key: str, feature_value: str) -> str:
    if feature_key.startswith("channel_stance:"):
        ch = feature_key.split(":", 1)[1]
        ch_ru = CHANNEL_LABELS.get(ch, ch)
        st_ru = STANCE_LABELS.get(feature_value, feature_value)
        return f"{ch_ru}: {st_ru}"
    if feature_key == "decision_criterion":
        return CRITERION_LABELS.get(feature_value, feature_value)
    if feature_key == "friction":
        return FRICTION_LABELS.get(feature_value, feature_value)
    if feature_key == "intent":
        return INTENT_LABELS.get(feature_value, feature_value)
    if feature_key == "contradiction":
        return f"противоречие ({feature_value})"
    return f"{feature_key}={feature_value}"


def stance_ru(stance: str) -> str:
    return STANCE_LABELS.get(stance, stance)
