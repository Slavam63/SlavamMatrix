
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import re
import shutil
import subprocess
import traceback
import zipfile
from zoneinfo import ZoneInfo

from flask import jsonify, redirect, render_template, request, url_for
from sqlalchemy import desc
from werkzeug.utils import secure_filename

import app
from app.models import JobRequest, Slot, Task, User, Vacancy, VacancyIntake
from app.resume_agent_profile import build_resume_agent_profile
from app.resume_domain import detect_product_domain
from app.resume_form_mapper import map_resume_to_form_data
from app.slots import ensure_slots, get_slots_list, get_celery_sender, reserve_slot
from app.status import get_job_request_status


ALLOWED_RESUME_EXTENSIONS = {"pdf", "doc", "docx", "rtf", "txt"}
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PARSING_CAPACITY = 4


def _normalize_keywords_input(keywords):
    if isinstance(keywords, list):
        return ", ".join(str(item).strip() for item in keywords if str(item).strip())
    if keywords is None:
        return ""
    return str(keywords).strip()


def _build_form_data_from_request(req):
    work_format = (req.form.get("work_format") or "").strip()
    return {
        "email": (req.form.get("email") or "").strip().lower(),
        "query_text": (req.form.get("query_text") or "").strip(),
        "position": (req.form.get("position") or "").strip(),
        "keywords": (req.form.get("keywords") or "").strip(),
        "location": (req.form.get("location") or "").strip(),
        "salary_min": (req.form.get("salary_min") or "").strip(),
        "salary_max": (req.form.get("salary_max") or "").strip(),
        "employment_type": (req.form.get("employment_type") or "").strip(),
        "work_format": work_format,
        "display_period": (req.form.get("display_period") or "").strip(),
        "sort_order": (req.form.get("sort_order") or "").strip(),
        "vacancy_source": (req.form.get("vacancy_source") or "").strip(),
        "remote": (work_format == "remote") or bool(req.form.get("remote")),
        "resume_autofill_done": (req.form.get("resume_autofill_done") or "").strip(),
        "resume_file_name": (req.form.get("resume_file_name") or "").strip(),
        "resume_file_path": (req.form.get("resume_file_path") or "").strip(),
        "resume_uploaded_at": (req.form.get("resume_uploaded_at") or "").strip(),
        "agent_clarification_question": (req.form.get("agent_clarification_question") or "").strip(),
        "agent_reasoning": (req.form.get("agent_reasoning") or "").strip(),
        "agent_primary_role": (req.form.get("agent_primary_role") or "").strip(),
        "agent_alternate_roles": (req.form.get("agent_alternate_roles") or "").strip(),
        "agent_primary_industry": (req.form.get("agent_primary_industry") or "").strip(),
        "agent_adjacent_contexts": (req.form.get("agent_adjacent_contexts") or "").strip(),
        "agent_confidence": (req.form.get("agent_confidence") or "").strip(),
    }


def _get_resume_upload_dir():
    return Path(__file__).resolve().parent / "uploads" / "resumes"


def _get_resume_extension(filename: str) -> str:
    normalized = (filename or "").strip()
    if not normalized or "." not in normalized:
        raise ValueError("Не удалось определить расширение файла резюме.")
    ext = normalized.rsplit(".", 1)[1].strip().lower()
    if not ext:
        raise ValueError("Не удалось определить расширение файла резюме.")
    return ext


def _allowed_resume_filename(filename: str) -> bool:
    try:
        ext = _get_resume_extension(filename)
    except ValueError:
        return False
    return ext in ALLOWED_RESUME_EXTENSIONS


def _save_resume_file(uploaded_file, user_email: str):
    if uploaded_file is None:
        return None, None, None
    original_name = (uploaded_file.filename or "").strip()
    if not original_name:
        return None, None, None
    if not _allowed_resume_filename(original_name):
        allowed_list = ", ".join(sorted(ALLOWED_RESUME_EXTENSIONS))
        raise ValueError(f"Недопустимый формат файла резюме. Разрешены: {allowed_list}.")
    safe_name = secure_filename(original_name)
    if not safe_name:
        raise ValueError("Не удалось обработать имя файла резюме.")
    ext = _get_resume_extension(original_name)
    email_prefix = secure_filename((user_email or "user").split("@")[0]) or "user"
    generated_name = f"{email_prefix}_{uuid4().hex}.{ext}"
    upload_dir = _get_resume_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / generated_name
    uploaded_file.save(destination)
    relative_path = f"uploads/resumes/{generated_name}"
    return original_name, relative_path, destination


def _extract_text_from_txt(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _extract_text_from_rtf(file_path: Path) -> str:
    raw = file_path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    text = re.sub(r"\\[a-zA-Z]+\d* ?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_text_from_docx(file_path: Path) -> str:
    parts = []
    with zipfile.ZipFile(file_path) as zf:
        with zf.open("word/document.xml") as doc:
            xml_text = doc.read().decode("utf-8", errors="ignore")
            xml_text = re.sub(r"</w:p>", "\n", xml_text)
            xml_text = re.sub(r"</w:tr>", "\n", xml_text)
            xml_text = re.sub(r"</w:tc>", " ", xml_text)
            xml_text = re.sub(r"<w:tab[^>]*/>", " ", xml_text)
            xml_text = re.sub(r"<w:br[^>]*/>", "\n", xml_text)
            xml_text = re.sub(r"<[^>]+>", " ", xml_text)
            xml_text = xml_text.replace("\xa0", " ")
            xml_text = re.sub(r"[ \t]+", " ", xml_text)
            xml_text = re.sub(r" *\n *", "\n", xml_text)
            xml_text = re.sub(r"\n{3,}", "\n\n", xml_text)
            parts.append(xml_text.strip())
    return "\n".join(parts).strip()


def _extract_text_from_pdf(file_path: Path) -> str:
    pdftotext_path = shutil.which("pdftotext") or "/usr/bin/pdftotext"
    try:
        result = subprocess.run(
            [pdftotext_path, str(file_path), "-"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _extract_text_from_doc(file_path: Path) -> str:
    try:
        result = subprocess.run(
            ["strings", str(file_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _extract_resume_text(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".txt":
        return _extract_text_from_txt(file_path)
    if ext == ".rtf":
        return _extract_text_from_rtf(file_path)
    if ext == ".docx":
        return _extract_text_from_docx(file_path)
    if ext == ".pdf":
        return _extract_text_from_pdf(file_path)
    if ext == ".doc":
        return _extract_text_from_doc(file_path)
    return ""


def _clean_resume_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_person_name(line: str) -> bool:
    cleaned = " ".join((line or "").strip().split())
    if not cleaned:
        return False
    lower_cleaned = cleaned.lower()
    role_phrases = (
        "chief information officer", "chief technical officer", "chief technology officer",
        "chief operating officer", "chief executive officer", "chief financial officer",
        "chief marketing officer", "chief product officer", "chief digital officer",
        "chief data officer", "chief security officer",
        "директор", "руководитель", "начальник", "manager", "lead", "developer",
        "engineer", "architect", "analyst", "consultant", "product owner",
        "product manager", "project manager", "tech lead", "team lead", "devops",
        "ceo", "cfo", "cto", "coo", "cio", "cmo", "chro",
    )
    if any(phrase in lower_cleaned for phrase in role_phrases):
        return False
    parts = cleaned.split()
    if len(parts) not in (2, 3):
        return False
    for part in parts:
        if len(part) < 2:
            return False
        if not re.fullmatch(r"[A-Za-zА-Яа-яЁё\-]+", part):
            return False
    upper_parts = sum(1 for part in parts if part[:1].isupper())
    return upper_parts == len(parts)


def _extract_email_from_text(text: str) -> str:
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, flags=re.I)
    return match.group(0).strip().lower() if match else ""


def _extract_salary_from_text(text: str) -> str:
    patterns = [
        r"(?:зарплат[аы]|доход|ожидани[ея]|expectation|salary)[^0-9]{0,20}(\d{2,7})",
        r"(\d{2,7})\s*(?:руб|₽)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1)
    return ""


def _extract_location_from_text(text: str) -> str:
    line_match = re.search(
        r"(?:проживает|город|локация|location|место проживания|место работы)\s*[:\-]?\s*([^\n\r]{2,80})",
        text, flags=re.I,
    )
    if line_match:
        value = " ".join(line_match.group(1).split())
        value = re.split(r"\s+(?:гражданство|есть разрешение|готов к переезду)\b", value, maxsplit=1, flags=re.I)[0].strip(" ,;.")
        if value:
            return value
    patterns = [
        r"\b(Москва|Санкт-Петербург|Петербург|Казань|Екатеринбург|Новосибирск|Краснодар|Нижний Новгород|Самара|Ростов-на-Дону|Калининград|Минск|Алматы|Ташкент|Тбилиси|Dubai|Abu Dhabi|Berlin|Frankfurt|Munich|Remote)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = match.group(1).strip() if match.lastindex else match.group(0).strip()
            if len(value) <= 80:
                return value
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:12]:
        if "|" in line:
            parts = [part.strip(" ,;.") for part in line.split("|")]
            for part in parts:
                if re.search(r"\b(Москва|Санкт-Петербург|Петербург|Казань|Екатеринбург|Новосибирск|Краснодар|Нижний Новгород|Самара|Ростов-на-Дону|Калининград|Минск|Алматы|Ташкент|Тбилиси|Dubai|Abu Dhabi|Berlin|Frankfurt|Munich)\b", part, flags=re.I):
                    return part
    return ""


def _extract_employment_type_from_text(text: str) -> str:
    patterns = [
        (r"тип занятости\s*:\s*полная", "full"),
        (r"тип занятости\s*:\s*частич", "part"),
        (r"тип занятости\s*:\s*проект", "project"),
        (r"полная занятость", "full"),
        (r"частичная занятость", "part"),
        (r"проектная работа", "project"),
    ]
    for pattern, value in patterns:
        if re.search(pattern, text, flags=re.I):
            return value
    return ""


def _extract_work_format_from_text(text: str) -> str:
    match = re.search(r"формат работы\s*:\s*([^\n]+)", text, flags=re.I)
    value = match.group(1).lower() if match else text.lower()
    found = []
    if "удален" in value or "удалён" in value or "remote" in value:
        found.append("remote")
    if "гибрид" in value:
        found.append("hybrid")
    if "разъезд" in value:
        found.append("travel")
    if "на месте работодателя" in value or "офис" in value:
        found.append("office")
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        return "hybrid"
    return ""


def _extract_position_from_text(text: str) -> str:
    explicit_patterns = [
        r"желаемая должность и зарплата\s+([^\n]{2,90})",
        r"специализации:\s*(?:—\s*)?([^\n]{2,90})",
        r"позиция\s*[:\-]?\s*([^\n]{2,90})",
        r"должность\s*[:\-]?\s*([^\n]{2,90})",
        r"position\s*[:\-]?\s*([^\n]{2,90})",
        r"objective\s*[:\-]?\s*([^\n]{2,90})",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = " ".join(match.group(1).split()).strip(" ,;.-")
            if value and not _looks_like_person_name(value):
                return value
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blacklist = (
        "@", "http://", "https://", "linkedin.com", "telegram", "телефон", "+7", "город",
        "локация", "location", "доход", "зарплат", "ключевые навыки", "опыт работы",
        "образование", "сертификаты", "курсы", "свидетельства", "медиаресурсы", "языки", "о себе",
    )
    strong_role_markers = (
        "chief information officer", "chief technical officer", "chief technology officer",
        "chief operating officer", "chief executive officer", "chief financial officer",
        "chief marketing officer", "chief product officer", "chief digital officer",
        "chief data officer", "chief security officer", "ceo", "cfo", "cto", "coo", "cio",
        "cmo", "chro", "директор", "руководител", "начальник", "head", "lead", "manager",
        "developer", "engineer", "architect", "analyst", "consultant", "product owner",
        "product manager", "project manager", "tech lead", "team lead", "devops",
    )
    for line in lines[:30]:
        lower_line = line.lower()
        if any(item in lower_line for item in blacklist):
            continue
        if _looks_like_person_name(line):
            continue
        if len(line) < 2 or len(line) > 90:
            continue
        if any(marker in lower_line for marker in strong_role_markers):
            return line
    for idx, line in enumerate(lines[:50]):
        lower_line = line.lower()
        if any(item in lower_line for item in blacklist):
            continue
        if _looks_like_person_name(line):
            continue
        if len(line) < 2 or len(line) > 90:
            continue
        if idx + 1 < len(lines):
            next_line = lines[idx + 1].strip()
            if "опыт работы" in next_line.lower() or re.search(r"\b\d{2}\.\d{2}\b", next_line):
                return line
    for line in lines[:20]:
        lower_line = line.lower()
        if any(item in lower_line for item in blacklist):
            continue
        if _looks_like_person_name(line):
            continue
        if len(line) < 2 or len(line) > 90:
            continue
        return line
    return ""


def _extract_keywords_from_text(text: str, position: str = "", query_text: str = "", product_domain: str = "unknown"):
    keyword_candidates = [
        "операционный директор", "coo", "директор по логистике", "логистика",
        "supply chain", "scm", "складская логистика", "транспортная логистика",
        "закупки", "бюджетирование", "бизнес-стратегия", "стратегическое планирование",
        "командообразование", "управление цепочкой поставок", "управление качеством",
        "управление затратами", "металлургия", "ритейл", "производство", "дистрибуция",
        "wms", "tms", "s&op", "ddmrp", "kpi", "3pl", "вэд",
        "python", "fastapi", "django", "flask", "sql", "postgresql", "docker",
        "backend", "frontend", "fullstack", "finance", "cfo", "ceo", "cto", "cio",
        "hr", "analytics", "data", "ai", "devops", "kubernetes", "1с", "erp", "bi",
        "it", "информационная безопасность", "кибербезопасность", "grafana", "zabbix",
        "go", "c++", "flutter", "retail", "lms", "ci/cd", "itil", "itsm",
    ]
    if product_domain == "it_product":
        keyword_candidates.extend([
            "product manager", "product owner", "head of product", "chief product officer",
            "директор по продукту", "руководитель продукта", "продакт-менеджер",
            "saas", "digital product", "roadmap", "backlog", "scrum", "agile",
            "product analytics", "ux", "ui", "api", "platform", "mobile app", "web app",
        ])
    elif product_domain == "food_product":
        keyword_candidates.extend([
            "продукты питания", "fmcg", "food", "retail", "horeca", "ассортимент",
            "закупки", "поставщики", "мерчендайзинг", "торговые сети", "дистрибуция",
            "consumer goods", "category manager", "procurement",
        ])
    found = []
    lower_text = text.lower()
    for item in keyword_candidates:
        if item in lower_text and item not in found:
            found.append(item)
    for item in [position, query_text]:
        item = (item or "").strip().lower()
        if item and item not in found:
            found.insert(0, item)
    return ", ".join(found[:15])


def _extract_query_text_from_text(text: str, position: str, product_domain: str = "unknown") -> str:
    lower_text = text.lower()
    if product_domain == "it_product":
        return "IT"
    if product_domain == "food_product":
        return "Продукты питания"
    explicit_industries = [
        (r"металлург", "Металлургия"),
        (r"металлообработ", "Металлургия"),
        (r"добывающ", "Добывающая отрасль"),
        (r"продукты питания", "Продукты питания"),
        (r"пищевая промышленность", "Продукты питания"),
        (r"пищевая продукция", "Продукты питания"),
        (r"\bfmcg\b", "Продукты питания"),
        (r"сельск", "Сельское хозяйство"),
        (r"розничн", "Retail"),
        (r"ритейл", "Retail"),
        (r"e-commerce", "Retail"),
        (r"логист", "Логистика"),
        (r"транспорт", "Логистика"),
        (r"склад", "Логистика"),
        (r"вэд", "Логистика"),
        (r"строител", "Строительство"),
        (r"фарм", "Фармацевтика"),
        (r"финанс", "Финансы"),
        (r"банк", "Финансы"),
        (r"\bit\b", "IT"),
        (r"информацион", "IT"),
        (r"разработ", "IT"),
        (r"цифров", "IT"),
        (r"kubernetes", "IT"),
        (r"devops", "IT"),
        (r"\bbi\b", "IT"),
        (r"1с", "IT"),
        (r"erp", "IT"),
        (r"product manager", "IT"),
        (r"product owner", "IT"),
        (r"head of product", "IT"),
        (r"director of product", "IT"),
        (r"saas", "IT"),
        (r"roadmap", "IT"),
        (r"backlog", "IT"),
    ]
    for pattern, value in explicit_industries:
        if re.search(pattern, lower_text, flags=re.I):
            return value
    if re.search(r"операцион|логист|supply chain|scm", lower_text, flags=re.I):
        return "Логистика"
    if re.search(r"chief information officer|chief technical officer|chief technology officer|cio|cto|информацион|цифров|devops|kubernetes|1с|erp|\bbi\b", lower_text, flags=re.I):
        return "IT"
    if position:
        return position
    return ""


def _parse_resume_to_form_data(text: str) -> dict:
    clean_text = _clean_resume_text(text)
    lower_text = clean_text.lower()
    mapped = map_resume_to_form_data(clean_text)
    position = (mapped.get("position") or "").strip()
    email = (mapped.get("email") or "").strip().lower()
    salary_min = (mapped.get("salary_min") or "").strip()
    location = (mapped.get("location") or "").strip()
    employment_type = (mapped.get("employment_type") or "").strip()
    work_format = (mapped.get("work_format") or "").strip()
    query_text = (mapped.get("query_text") or "").strip()
    keywords = (mapped.get("keywords") or "").strip()
    product_domain_info = detect_product_domain(clean_text)
    product_domain = product_domain_info.get("product_domain", "unknown")
    if not position:
        position = _extract_position_from_text(clean_text)
    if not email:
        email = _extract_email_from_text(clean_text)
    if not salary_min:
        salary_min = _extract_salary_from_text(clean_text)
    if not location:
        location = _extract_location_from_text(clean_text)
    if not employment_type:
        employment_type = _extract_employment_type_from_text(clean_text)
    if not work_format:
        work_format = _extract_work_format_from_text(clean_text)
    if not query_text:
        query_text = _extract_query_text_from_text(clean_text, position, product_domain)
    if not keywords:
        keywords = _extract_keywords_from_text(clean_text, position, query_text, product_domain)
    remote = bool(mapped.get("remote")) or ("remote" in lower_text) or ("удален" in lower_text) or ("удалён" in lower_text) or (work_format == "remote")
    return {
        "email": email,
        "query_text": query_text,
        "position": position,
        "keywords": keywords,
        "location": location,
        "salary_min": salary_min,
        "salary_max": "",
        "employment_type": employment_type,
        "work_format": work_format,
        "display_period": "",
        "sort_order": "",
        "vacancy_source": "",
        "remote": remote,
    }


def _is_bad_value(value) -> bool:
    if value is None:
        return True
    text = str(value).strip().lower()
    if not text:
        return True
    bad_exact = {"и зарплата", "зарплата", "и заработная плата", "заработная плата"}
    return text in bad_exact


def _split_keywords_value(value) -> list[str]:
    if not value:
        return []
    return [item.strip().lower() for item in str(value).split(",") if item.strip()]


def _should_replace_keywords(current_value, new_value) -> bool:
    if _is_bad_value(current_value):
        return True
    current_items = _split_keywords_value(current_value)
    new_items = _split_keywords_value(new_value)
    if not new_items:
        return False
    current_text = ", ".join(current_items)
    new_text = ", ".join(new_items)
    strong_market_markers = {
        "commercial strategy", "revenue growth", "key account management",
        "pipeline management", "sales management", "channel sales",
        "international sales", "partnerships", "p&l",
    }
    legacy_generic_markers = {
        "продажи", "развитие бизнеса", "переговоры", "стратегия",
        "маркетинг", "crm", "b2b", "key account",
    }
    current_has_legacy_generic = any(marker in current_text for marker in legacy_generic_markers)
    new_has_strong_market = any(marker in new_text for marker in strong_market_markers)
    overlap = len(set(current_items) & set(new_items))
    if new_has_strong_market and current_has_legacy_generic and overlap < 4:
        return True
    if len(current_items) <= 4 and len(new_items) >= 6:
        return True
    return False


def _merge_form_data_with_resume_data(form_data: dict, resume_data: dict) -> dict:
    merged = dict(form_data)
    for key, value in resume_data.items():
        current_value = merged.get(key)
        if key == "remote":
            if not current_value and value:
                merged[key] = True
            continue
        if key == "keywords":
            if _should_replace_keywords(current_value, value):
                merged[key] = value
            continue
        if _is_bad_value(current_value) and value:
            merged[key] = value
    return merged


def _merge_form_data_with_agent_profile(form_data: dict, agent_profile: dict) -> dict:
    merged = dict(form_data)
    recommended = agent_profile.get("recommended_form_fields") or {}
    for key, value in recommended.items():
        current_value = merged.get(key)
        if key == "remote":
            if not current_value and value:
                merged[key] = True
            continue
        if key == "keywords":
            if _should_replace_keywords(current_value, value):
                merged[key] = value
            continue
        if _is_bad_value(current_value) and value:
            merged[key] = value
    merged["agent_primary_role"] = agent_profile.get("primary_role") or ""
    merged["agent_alternate_roles"] = ", ".join(agent_profile.get("alternate_roles") or [])
    merged["agent_primary_industry"] = agent_profile.get("primary_industry") or ""
    merged["agent_adjacent_contexts"] = ", ".join(agent_profile.get("adjacent_contexts") or [])
    merged["agent_clarification_question"] = agent_profile.get("clarification_question") or ""
    merged["agent_reasoning"] = agent_profile.get("reasoning") or ""
    merged["agent_confidence"] = str(agent_profile.get("confidence") or "")
    return merged


def _get_reserved_slot_for_job_request(job_request: JobRequest):
    db = app.db_session
    if not job_request:
        return None
    slot = (
        db.query(Slot)
        .filter(Slot.job_request_id == job_request.id, Slot.status == "reserved")
        .order_by(desc(Slot.slot_time), desc(Slot.id))
        .first()
    )
    if slot is not None:
        return slot
    if not job_request.user_id:
        return None
    return (
        db.query(Slot)
        .filter(Slot.reserved_by == job_request.user_id, Slot.job_request_id.is_(None), Slot.status == "reserved")
        .order_by(desc(Slot.slot_time), desc(Slot.id))
        .first()
    )


def _count_active_tasks() -> int:
    db = app.db_session
    return db.query(Task).filter(Task.status.in_(["queued", "running"])).count()


def _create_job_request_task_record(db, job_request: JobRequest) -> Task:
    task = Task(job_request_id=job_request.id, status="queued", progress=0, found_vacancies=0)
    db.add(task)
    job_request.status = "queued"
    db.flush()
    return task


def _dispatch_job_request_task(db, task: Task) -> Task:
    celery_client = get_celery_sender()
    async_result = celery_client.send_task("app.tasks.process_job_request", args=[task.id])
    task.celery_task_id = async_result.id
    db.flush()
    return task


def _cancel_job_request_and_release_slot(db, job_request: JobRequest) -> bool:
    if not job_request:
        return False
    terminal_request_statuses = {"completed", "done", "failed", "cancelled"}
    if (job_request.status or "").strip().lower() not in terminal_request_statuses:
        job_request.status = "cancelled"
    active_task_statuses = {"pending", "queued", "waiting", "running", "started", "processing", "slot_selection", "created"}
    tasks = db.query(Task).filter(Task.job_request_id == job_request.id).order_by(desc(Task.created_at), desc(Task.id)).all()
    for task in tasks:
        current_status = (task.status or "").strip().lower()
        if current_status not in {"completed", "done", "failed", "cancelled"}:
            if current_status in active_task_statuses or not current_status:
                task.status = "cancelled"
                if task.finished_at is None:
                    task.finished_at = datetime.now(timezone.utc)
    slots = db.query(Slot).filter(Slot.job_request_id == job_request.id).all()
    for slot in slots:
        slot.status = "free"
        slot.reserved_by = None
        slot.job_request_id = None
    db.flush()
    return True


def _extract_manual_title(raw_text: str, explicit_title: str = "") -> str:
    title = (explicit_title or "").strip()
    if title:
        return title[:500]
    for line in (raw_text or "").splitlines():
        cleaned = " ".join(line.split()).strip(" -–—")
        if cleaned:
            return cleaned[:500]
    return "Manual vacancy"


def register_routes(flask_app):

    @flask_app.route("/api/v1/job-request", methods=["POST"])
    def create_job_request():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        query_text = (data.get("query_text") or "").strip()
        position = (data.get("position") or "").strip()
        keywords = data.get("keywords")
        location = (data.get("location") or "").strip()
        salary_min = data.get("salary_min")
        salary_max = data.get("salary_max")
        employment_type = (data.get("employment_type") or "").strip()
        work_format = (data.get("work_format") or "").strip()
        display_period = (data.get("display_period") or "").strip()
        sort_order = (data.get("sort_order") or "").strip()
        vacancy_source = (data.get("vacancy_source") or "").strip()
        remote = bool(data.get("remote", False)) or work_format == "remote"

        if not email:
            return jsonify({"error": "email is required"}), 400

        db = app.db_session
        try:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                user = User(email=email)
                db.add(user)
                db.flush()
            keywords = _normalize_keywords_input(keywords)
            job_request = JobRequest(
                user_id=user.id,
                query_text=query_text or None,
                position=position or None,
                keywords=keywords or None,
                location=location or None,
                salary_min=salary_min,
                salary_max=salary_max,
                employment_type=employment_type or None,
                work_format=work_format or None,
                display_period=display_period or None,
                sort_order=sort_order or None,
                vacancy_source=vacancy_source or None,
                remote=remote,
                status="created",
            )
            db.add(job_request)
            db.commit()
            return jsonify({"job_request_id": job_request.id, "status": job_request.status}), 201
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/v1/vacancy-intake/manual", methods=["POST"])
    def create_manual_vacancy_intake():
        data = request.get_json(silent=True) or {}
        job_request_id = data.get("job_request_id")
        raw_text = (data.get("raw_text") or "").strip()
        title = (data.get("title") or "").strip()
        company = (data.get("company") or "").strip()
        location = (data.get("location") or "").strip()
        source_url = (data.get("source_url") or data.get("url") or "").strip()
        employment_type = (data.get("employment_type") or "").strip()
        remote = bool(data.get("remote", False))
        source_name = (data.get("source_name") or "manual").strip()

        if not job_request_id:
            return jsonify({"error": "job_request_id is required"}), 400
        if not raw_text and not title:
            return jsonify({"error": "raw_text or title is required"}), 400

        db = app.db_session
        try:
            job_request = db.query(JobRequest).filter(JobRequest.id == int(job_request_id)).first()
            if not job_request:
                return jsonify({"error": "job request not found"}), 404

            parsed_title = _extract_manual_title(raw_text=raw_text, explicit_title=title)
            intake = VacancyIntake(
                job_request_id=job_request.id,
                source_type="manual",
                source_name=source_name or "manual",
                status="received",
                raw_subject=title or parsed_title,
                raw_text=raw_text or title or parsed_title,
                source_url=source_url or None,
                parsed_title=parsed_title,
                parsed_company=company or None,
                parsed_location=location or None,
                parsed_employment_type=employment_type or None,
                parsed_remote=remote,
                parser_version="manual_v1",
            )
            db.add(intake)
            db.flush()

            vacancy = Vacancy(
                job_request_id=job_request.id,
                source="manual",
                external_id=f"manual-intake-{intake.id}",
                title=parsed_title,
                company=company or None,
                location=location or None,
                salary=None,
                url=source_url or f"manual://vacancy-intake/{intake.id}",
                description=raw_text or None,
                employment_type=employment_type or None,
                remote=remote,
                ai_score=None,
                ai_summary=None,
                ai_tags=None,
            )
            db.add(vacancy)
            intake.status = "processed"
            intake.processed_at = datetime.now(timezone.utc)
            db.commit()

            return jsonify({
                "ok": True,
                "job_request_id": job_request.id,
                "vacancy_intake_id": intake.id,
                "vacancy_id": vacancy.id,
                "status": intake.status,
                "source": "manual",
            }), 201
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/v1/job-request/<int:job_request_id>/cancel", methods=["POST"])
    def cancel_job_request(job_request_id):
        db = app.db_session
        try:
            job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
            if not job_request:
                return jsonify({"error": "job request not found"}), 404
            _cancel_job_request_and_release_slot(db, job_request)
            db.commit()
            return jsonify({"job_request_id": job_request.id, "status": job_request.status, "cancelled": True}), 200
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/v1/verify-email", methods=["POST"])
    def verify_email():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email:
            return jsonify({"error": "email is required"}), 400
        db = app.db_session
        try:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                return jsonify({"error": "user not found"}), 404
            job_request = db.query(JobRequest).filter(JobRequest.user_id == user.id).order_by(desc(JobRequest.created_at), desc(JobRequest.id)).first()
            if not job_request:
                return jsonify({"error": "job request not found"}), 404
            return jsonify({"job_request_id": job_request.id, "status": job_request.status}), 200
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/v1/slots", methods=["GET"])
    def get_slots():
        db = app.db_session
        try:
            ensure_slots()
            slots = get_slots_list()
            db.commit()
            return jsonify(slots), 200
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/v1/slots/reserve", methods=["POST"])
    def reserve_slots_route():
        data = request.get_json(silent=True) or {}
        job_request_id = data.get("job_request_id")
        slot_id = data.get("slot_id")
        if not job_request_id:
            return jsonify({"error": "job_request_id is required"}), 400
        if not slot_id:
            return jsonify({"error": "slot_id is required"}), 400
        db = app.db_session
        try:
            result = reserve_slot(int(job_request_id), int(slot_id))
            return jsonify(result), 200
        except ValueError as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/v1/status/<int:job_request_id>", methods=["GET"])
    def get_status(job_request_id):
        db = app.db_session
        try:
            result = get_job_request_status(job_request_id)
            db.commit()
            return jsonify(result), 200
        except ValueError as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/v1/vacancies/<int:job_request_id>", methods=["GET"])
    def get_vacancies(job_request_id):
        db = app.db_session
        try:
            job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
            if not job_request:
                return jsonify({"error": "job request not found"}), 404
            vacancies = db.query(Vacancy).filter(Vacancy.job_request_id == job_request_id).order_by(desc(Vacancy.created_at), desc(Vacancy.id)).all()
            result = []
            for vacancy in vacancies:
                result.append({
                    "id": vacancy.id,
                    "job_request_id": vacancy.job_request_id,
                    "source": vacancy.source,
                    "external_id": vacancy.external_id,
                    "title": vacancy.title,
                    "company": vacancy.company,
                    "location": vacancy.location,
                    "salary": vacancy.salary,
                    "url": vacancy.url,
                    "description": vacancy.description,
                    "employment_type": vacancy.employment_type,
                    "remote": vacancy.remote,
                    "ai_score": float(vacancy.ai_score) if vacancy.ai_score is not None else None,
                    "ai_summary": vacancy.ai_summary,
                    "ai_tags": vacancy.ai_tags,
                    "posted_at": vacancy.posted_at.isoformat() if vacancy.posted_at else None,
                    "created_at": vacancy.created_at.isoformat() if vacancy.created_at else None,
                })
            db.commit()
            return jsonify(result), 200
        except Exception as exc:
            db.rollback()
            return jsonify({"error": str(exc)}), 500

    @flask_app.route("/job-search", methods=["GET", "POST"])
    def job_search_page():
        db = app.db_session
        if request.method == "GET":
            return render_template("job_search_form.html", form_data={}, error_message=None, success_message=None)
        form_data = _build_form_data_from_request(request)
        uploaded_resume = request.files.get("resume_file")
        form_action = (request.form.get("form_action") or "").strip()
        try:
            if form_action == "upload_resume_data":
                if not uploaded_resume or not (uploaded_resume.filename or "").strip():
                    return render_template("job_search_form.html", form_data=form_data, error_message="Сначала выберите файл резюме, затем нажмите «ЗАГРУЗИТЬ ДАННЫЕ».", success_message=None), 400
            if form_action == "upload_resume_data" and uploaded_resume and (uploaded_resume.filename or "").strip():
                email_for_file = form_data["email"] or "user@matrix.local"
                resume_file_name, resume_file_path, saved_file_path = _save_resume_file(uploaded_resume, email_for_file)
                resume_uploaded_at = datetime.now(timezone.utc).isoformat()
                fallback_form_data = dict(form_data)
                fallback_form_data["resume_autofill_done"] = ""
                fallback_form_data["resume_file_name"] = resume_file_name or ""
                fallback_form_data["resume_file_path"] = resume_file_path or ""
                fallback_form_data["resume_uploaded_at"] = resume_uploaded_at
                try:
                    resume_text = _extract_resume_text(saved_file_path)
                    clean_resume_text = _clean_resume_text(resume_text)
                    agent_profile = build_resume_agent_profile(resume_text=clean_resume_text, current_form_data=form_data)
                    merged_form_data = _merge_form_data_with_agent_profile(form_data, agent_profile)
                    merged_form_data["resume_autofill_done"] = "1"
                    merged_form_data["resume_file_name"] = resume_file_name or ""
                    merged_form_data["resume_file_path"] = resume_file_path or ""
                    merged_form_data["resume_uploaded_at"] = resume_uploaded_at
                    has_minimum_data = bool((merged_form_data.get("position") or "").strip() and (merged_form_data.get("email") or "").strip())
                    clarification_question = merged_form_data.get("agent_clarification_question") or ""
                    if has_minimum_data:
                        success_message = ("Агент проанализировал резюме и подготовил рекомендуемое заполнение формы. "
                                           "Проверьте поля перед поиском. "
                                           f"{clarification_question}").strip()
                        error_message = None
                    else:
                        success_message = None
                        error_message = "Агент обработал резюме, но не смог надёжно определить минимум для продолжения: должность и e-mail. Пожалуйста, заполните их вручную."
                    return render_template("job_search_form.html", form_data=merged_form_data, error_message=error_message, success_message=success_message), 200
                except Exception:
                    flask_app.logger.error("Resume autofill failed for uploaded file '%s':\n%s", resume_file_name or "", traceback.format_exc())
                    return render_template("job_search_form.html", form_data=fallback_form_data, error_message="Резюме загружено, но автоматическое заполнение формы не удалось выполнить. Пожалуйста, заполните поля вручную.", success_message=None), 200

            if not form_data["email"]:
                return render_template("job_search_form.html", form_data=form_data, error_message="Пожалуйста, укажите email.", success_message=None), 400
            user = db.query(User).filter(User.email == form_data["email"]).first()
            if not user:
                user = User(email=form_data["email"])
                db.add(user)
                db.flush()
            salary_min = int(form_data["salary_min"]) if form_data["salary_min"] else None
            salary_max = int(form_data["salary_max"]) if form_data["salary_max"] else None
            resume_file_name = form_data["resume_file_name"] or None
            resume_file_path = form_data["resume_file_path"] or None
            resume_uploaded_at = None
            if form_data["resume_uploaded_at"]:
                try:
                    resume_uploaded_at = datetime.fromisoformat(form_data["resume_uploaded_at"])
                except Exception:
                    resume_uploaded_at = datetime.now(timezone.utc)
            if uploaded_resume and (uploaded_resume.filename or "").strip():
                resume_file_name, resume_file_path, _saved_file_path = _save_resume_file(uploaded_resume, form_data["email"])
                resume_uploaded_at = datetime.now(timezone.utc)

            job_request = JobRequest(
                user_id=user.id,
                query_text=form_data["query_text"] or None,
                position=form_data["position"] or None,
                keywords=_normalize_keywords_input(form_data["keywords"]) or None,
                location=form_data["location"] or None,
                salary_min=salary_min,
                salary_max=salary_max,
                employment_type=form_data["employment_type"] or None,
                work_format=form_data["work_format"] or None,
                display_period=form_data["display_period"] or None,
                sort_order=form_data["sort_order"] or None,
                vacancy_source=form_data["vacancy_source"] or None,
                remote=form_data["remote"],
                status="created",
                resume_file_name=resume_file_name,
                resume_file_path=resume_file_path,
                resume_uploaded_at=resume_uploaded_at,
            )
            db.add(job_request)
            db.flush()

            active_tasks_count = _count_active_tasks()
            if active_tasks_count < PARSING_CAPACITY:
                task = _create_job_request_task_record(db, job_request)
                db.commit()
                try:
                    _dispatch_job_request_task(db, task)
                    db.commit()
                except Exception:
                    db.rollback()
                    task = db.query(Task).filter(Task.id == task.id).first()
                    if task is not None:
                        task.status = "failed"
                        task.error_message = "Не удалось отправить задачу в очередь Celery."
                        task.finished_at = datetime.now(timezone.utc)
                    job_request = db.query(JobRequest).filter(JobRequest.id == job_request.id).first()
                    if job_request is not None:
                        job_request.status = "failed"
                    db.commit()
                    return render_template("job_search_form.html", form_data=form_data, error_message="Не удалось запустить задачу парсинга. Пожалуйста, попробуйте ещё раз.", success_message=None), 500
                return redirect(url_for("job_parsing_page", job_request_id=job_request.id))
            job_request.status = "slot_selection"
            db.commit()
            return redirect(url_for("job_slots_page", job_request_id=job_request.id))
        except ValueError as exc:
            db.rollback()
            return render_template("job_search_form.html", form_data=form_data, error_message=str(exc), success_message=None), 400
        except Exception as exc:
            db.rollback()
            flask_app.logger.error("Job request creation failed:\n%s", traceback.format_exc())
            return render_template("job_search_form.html", form_data=form_data, error_message=f"Не удалось создать запрос: {exc}", success_message=None), 500

    @flask_app.route("/job-slots/<int:job_request_id>", methods=["GET"])
    def job_slots_page(job_request_id):
        db = app.db_session
        try:
            job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
            if not job_request:
                return "job request not found", 404
            if (job_request.status or "").strip().lower() != "slot_selection":
                db.commit()
                return redirect(url_for("job_parsing_page", job_request_id=job_request.id))
            ensure_slots()
            slots = get_slots_list()
            user_email = job_request.user.email if job_request.user else None
            response = render_template("job_slots.html", job_request=job_request, slots=slots, user_email=user_email)
            db.commit()
            return response, 200
        except Exception as exc:
            db.rollback()
            return f"internal error: {exc}", 500

    @flask_app.route("/job-waiting/<int:job_request_id>", methods=["GET"])
    def job_waiting_page(job_request_id):
        db = app.db_session
        try:
            job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
            if not job_request:
                return "job request not found", 404
            user_email = job_request.user.email if job_request.user else None
            reserved_slot = _get_reserved_slot_for_job_request(job_request)
            slot_label = None
            waiting_until_iso = None
            if reserved_slot:
                slot_time_moscow = reserved_slot.slot_time.astimezone(MOSCOW_TZ)
                slot_label = slot_time_moscow.strftime("%d.%m.%Y %H:%M МСК")
                waiting_until_iso = reserved_slot.slot_time.isoformat()
            response = render_template("job_waiting.html", job_request=job_request, user_email=user_email, slot_label=slot_label, waiting_until_iso=waiting_until_iso)
            db.commit()
            return response, 200
        except Exception as exc:
            db.rollback()
            return f"internal error: {exc}", 500

    @flask_app.route("/job-parsing/<int:job_request_id>", methods=["GET"])
    def job_parsing_page(job_request_id):
        db = app.db_session
        try:
            job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
            if not job_request:
                return "job request not found", 404
            response = render_template("job_parsing.html", job_request=job_request)
            db.commit()
            return response, 200
        except Exception as exc:
            db.rollback()
            return f"internal error: {exc}", 500

    @flask_app.route("/job-results/<int:job_request_id>", methods=["GET"])
    def job_results_page(job_request_id):
        db = app.db_session
        try:
            job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
            if not job_request:
                return "job request not found", 404
            vacancies = db.query(Vacancy).filter(Vacancy.job_request_id == job_request_id).order_by(desc(Vacancy.created_at), desc(Vacancy.id)).all()
            status_info = get_job_request_status(job_request_id)
            user_email = job_request.user.email if job_request.user else None
            response = render_template("job_results.html", job_request=job_request, vacancies=vacancies, status_info=status_info, user_email=user_email)
            db.commit()
            return response, 200
        except ValueError:
            db.rollback()
            return "job request not found", 404
        except Exception as exc:
            db.rollback()
            return f"internal error: {exc}", 500

    @flask_app.route("/job-requests", methods=["GET"])
    def job_requests_page():
        db = app.db_session
        try:
            job_requests = db.query(JobRequest).order_by(desc(JobRequest.created_at), desc(JobRequest.id)).all()
            rows = []
            for job_request in job_requests:
                status_info = get_job_request_status(job_request.id)
                user_email = job_request.user.email if job_request.user else None
                rows.append({"job_request": job_request, "status_info": status_info, "user_email": user_email})
            response = render_template("job_requests.html", rows=rows)
            db.commit()
            return response, 200
        except Exception as exc:
            db.rollback()
            return f"internal error: {exc}", 500

