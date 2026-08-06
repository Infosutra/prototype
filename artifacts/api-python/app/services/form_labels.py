from __future__ import annotations

from typing import Any

META_TYPES = {
    "start",
    "end",
    "begin_group",
    "end_group",
    "begin_repeat",
    "end_repeat",
    "calculate",
    "note",
}


def get_form_translations(form_definition: dict[str, Any] | None) -> list[str]:
    if not form_definition:
        return []
    translations = form_definition.get("translations") or []
    return [str(t).strip() for t in translations if str(t).strip()]


def resolve_label_language(
    preferred: str | None,
    form_definition: dict[str, Any] | None,
) -> str | None:
    available = get_form_translations(form_definition)
    if not available:
        return (preferred or "").strip() or None

    if preferred:
        for lang in available:
            if lang.lower() == preferred.strip().lower():
                return lang

    for lang in available:
        if lang.lower() == "english":
            return lang

    settings = (form_definition or {}).get("settings") or {}
    default = settings.get("default_language")
    if isinstance(default, str):
        for lang in available:
            if lang.lower() == default.strip().lower():
                return lang

    return available[0]


def pick_translated_label(
    value: Any,
    form_definition: dict[str, Any] | None,
    preferred_language: str | None,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        language = resolve_label_language(preferred_language, form_definition)
        translations = get_form_translations(form_definition)
        if language and translations:
            try:
                index = next(
                    i
                    for i, lang in enumerate(translations)
                    if lang.lower() == language.lower()
                )
            except StopIteration:
                index = -1
            if 0 <= index < len(value):
                picked = pick_translated_label(
                    value[index], form_definition, preferred_language
                )
                if picked:
                    return picked
        for item in value:
            picked = pick_translated_label(item, form_definition, preferred_language)
            if picked:
                return picked
        return None
    if isinstance(value, dict):
        for item in value.values():
            picked = pick_translated_label(item, form_definition, preferred_language)
            if picked:
                return picked
    return None


def _find_field_value(data: dict[str, Any], field_name: str) -> Any:
    if field_name in data:
        return data[field_name]
    suffix = f"/{field_name}"
    for key, value in data.items():
        if key == field_name or key.endswith(suffix):
            return value
    return None


def first_survey_question(
    form_definition: dict[str, Any] | None,
) -> tuple[str, str | None] | None:
    survey = (form_definition or {}).get("survey")
    if not isinstance(survey, list):
        return None
    for item in survey:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        qtype = item.get("type")
        if not isinstance(name, str) or not isinstance(qtype, str):
            continue
        if qtype in META_TYPES:
            continue
        list_name = item.get("select_from_list_name")
        return name, list_name if isinstance(list_name, str) else None
    return None


def clean_enumerator_name(raw: str) -> str:
    return " ".join(raw.replace("_", " ").split()).strip()


def extract_enumerator_name(
    data: dict[str, Any],
    form_definition: dict[str, Any] | None,
) -> str | None:
    first = first_survey_question(form_definition)
    if not first:
        return None
    name, list_name = first
    raw = _find_field_value(data, name)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # Resolve select choice label (prefer English for reports).
    if list_name and form_definition:
        choices = form_definition.get("choices") or []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if choice.get("list_name") != list_name or choice.get("name") != text:
                continue
            label = pick_translated_label(choice.get("label"), form_definition, "English")
            if label:
                return clean_enumerator_name(label)
    return clean_enumerator_name(text) or None


def build_form_responses(
    data: dict[str, Any],
    form_definition: dict[str, Any] | None,
    preferred_language: str | None = None,
) -> list[dict[str, Any]]:
    survey = (form_definition or {}).get("survey")
    if not isinstance(survey, list):
        return []

    language = resolve_label_language(preferred_language, form_definition)
    choice_maps: dict[str, dict[str, str]] = {}
    choices = (form_definition or {}).get("choices") or []
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            list_name = choice.get("list_name")
            choice_name = choice.get("name")
            if not isinstance(list_name, str) or not isinstance(choice_name, str):
                continue
            label = (
                pick_translated_label(choice.get("label"), form_definition, language)
                or choice_name
            )
            choice_maps.setdefault(list_name, {})[choice_name] = label

    questions: dict[str, dict[str, Any]] = {}
    for item in survey:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        qtype = item.get("type")
        if not isinstance(name, str) or not isinstance(qtype, str):
            continue
        if qtype in META_TYPES:
            continue
        list_name = item.get("select_from_list_name")
        questions[name] = {
            "label": pick_translated_label(item.get("label"), form_definition, language)
            or name,
            "question_type": qtype,
            "list_name": list_name if isinstance(list_name, str) else None,
        }

    responses: list[dict[str, Any]] = []
    for key, value in data.items():
        field_name = key.split("/")[-1]
        question = questions.get(field_name)
        if not question:
            continue
        display = value
        list_name = question["list_name"]
        if list_name and str(question["question_type"]).startswith("select_"):
            mapping = choice_maps.get(list_name, {})
            if isinstance(value, str):
                parts = value.split()
                if len(parts) <= 1:
                    display = mapping.get(value, value)
                else:
                    display = ", ".join(mapping.get(p, p) for p in parts)
            elif isinstance(value, list):
                display = [mapping.get(v, v) if isinstance(v, str) else v for v in value]
        responses.append(
            {
                "key": key,
                "label": question["label"],
                "question_type": question["question_type"],
                "value": display,
            }
        )
    return responses
