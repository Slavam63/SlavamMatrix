# Matrix Parser — аудит источников вакансий (компакт)

**Проект:** `/var/www/matrix-parser`  
**Фокус:** почему мало вакансий (без UI / без изменений AI-агента в коде).

---

## 1. Список источников

| Что | Где |
|-----|-----|
| Env: порядок не-hh | `app/config.py` → `PARSER_DEFAULT_SOURCES` (дефолт `linkedin,mock`) |
| Env: HH / mock | `ENABLE_HH_SOURCE`, `ENABLE_MOCK_SOURCE` |
| Сборка списка для парсера | `app/parser.py` → `_get_enabled_sources()` |
| Тот же список в Celery/UI | `app/tasks.py` → `process_job_request` → `_get_enabled_sources()` |

**Правила `_get_enabled_sources()`:**  
`hh` только если `ENABLE_HH_SOURCE`; из `PARSER_DEFAULT_SOURCES` берутся `linkedin`, `mock` (если флаг), `manual`; строка `hh` в списке env игнорируется (hh только через флаг).

**Раннеры:** `app/parser.py` → `_run_source_with_status` — только `hh`, `linkedin`, `mock`, `manual`.

**`"all"`** в `app/search_agent.py` (`SOURCE_PRIORITY_BY_DOMAIN`) и `ALLOWED_SOURCE_NAMES` в `parser.py` — **не отдельный источник**, в `_run_source_with_status` ветки нет.

---

## 2. LinkedIn

**Цепочка:** `run_parser` → `_run_linkedin_with_scenarios` (`parser.py`) → `search_linkedin_vacancies` (`linkedin_source.py`) → `fetch_linkedin_jobs_via_bridge` (`linkedin_bridge.py`, Playwright).

**Статус `no_results`:** `parser.py` → `_run_source_with_status`: пустой список → `no_results` + общее сообщение (нет различения auth / DOM / ошибки).

**Условия 0 результатов:**

- Пустой эффективный query → `fetch_linkedin_jobs_via_bridge` early `[]`
- `_detect_linkedin_auth_state` → не залогинен → `[]` (без явной причины наружу)
- 0 карточек по селекторам или карточки без title/url
- `except` вокруг Playwright → `[]` (ошибка не пробрасывается как `failed` для источника)

**Прокси:** `config.py` (`LINKEDIN_PROXY_*`, `EFFECTIVE_LINKEDIN_PROXY_URL`); `get_linkedin_proxy_config()` + `_build_playwright_proxy_settings` в `linkedin_bridge.py` — Playwright **без прокси**, если `enabled=False`.

**Лимиты/DOM:** `LINKEDIN_JOBS_MAX_*`, scroll env в `config.py`; селекторы `li.jobs-search-results__list-item`, `scaffold-layout__list-item`, `ul.jobs-search__results-list li` и т.д. в `linkedin_bridge.py`.

**Mock LinkedIn:** `_mock_linkedin_results_for_job` в `linkedin_source.py` **не вызывается** в активном `search_linkedin_vacancies`.

---

## 3. HH

**Порядок:** `search_hh_vacancies` (`hh_source.py`) — при `HH_BROWSER_SOURCE_ENABLED` сначала `search_hh_vacancies_via_browser` (`hh_browser_source.py`).

**Критично:** успешный `return search_hh_vacancies_via_browser(...)` с **`[]`** завершает функцию — **API не вызывается** (нет fallback при «пустом успехе» браузера).

**Браузер:** `_build_hh_url`, `_detect_hh_state` (blocked/auth/ready), лимит `HH_JOBS_MAX_CARDS` (дефолт 20). `blocked`/`auth_required` → `HHBrowserSourceError` → `HHSourceError` (видимый статус).

**API:** `_build_hh_params`, `per_page = min(PARSER_RESULTS_LIMIT, 50)`; жёсткий отсев **`_is_relevant_vacancy`** + сортировка по score.

---

## 4. Агрегация

`parser.py` → `run_parser`: `extend` по источникам → `_deduplicate_vacancies` → `_apply_final_post_ranking` (`_should_keep_final_vacancy`, при пустоте fallback; mock отбрасывается при наличии внешних) → **`vacancies[:PARSER_RESULTS_LIMIT]`** (дефолт 50).  
Сохранение: `tasks.py` по данным после этого пайплайна.

---

## 5. Логирование (пробелы)

Нет структурных логов: сырой счёт по источнику до/после фильтра в `parser.py` / `tasks.py`.  
LinkedIn: тихий `[]` при not auth и в `except`.  
HH API: нет «N items → M после relevance».  
Нет сравнения длины до/после `_apply_final_post_ranking`.

---

## A) Реально подключаемые к циклу

`linkedin` (если в `PARSER_DEFAULT_SOURCES`), `mock` (флаг + список), `hh` (только `ENABLE_HH_SOURCE=1`), `manual` (в списке + данные VacancyIntake).

## B) Недоподключённые / не-раннеры

`hh` при `ENABLE_HH_SOURCE=0`; токен `"all"` в стратегии; mock LinkedIn в коде не используется; неизвестные строки в env-списке игнорируются.

## C) Точка отказа LinkedIn (приоритет)

1. Auth / challenge → ранний `[]`  
2. Блокировки / IP (прокси выкл. усиливает риск)  
3. Пустой query  
4. Сломанные селекторы → 0 карточек  
5. Исключение Playwright → `[]` без `failed`

## D) Ограничения HH

Браузер-first + пустой успех без API; API relevance; лимиты карт/страниц; общий `PARSER_RESULTS_LIMIT`.

## E) Главная причина «мало вакансий»

**Типичный конфиг:** HH выключен → остаются LinkedIn (часто 0: auth/DOM/блок) + mock (1).  
**LinkedIn:** пустой ответ неотличим от «реально пусто» (`no_results`).  
**HH (если вкл.):** нет API fallback при пустом браузере; API режет `_is_relevant_vacancy`.  
**Агрегация:** dedup + финальный фильтр + лимит 50 — вторично относительно «источник вернул мало/ноль».

---

*Файл для копирования/скачивания: `docs/VACANCY_SOURCES_AUDIT.md`*
