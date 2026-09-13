from __future__ import annotations

import re
from collections import defaultdict
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

# Extra types that must never be treated as the enumerator identity field.
ENUMERATOR_SKIP_TYPES = META_TYPES | {
    "today",
    "datetime",
    "date",
    "time",
    "username",
    "deviceid",
    "phonenumber",
    "audit",
    "simserial",
    "subscriberid",
    "imei",
}

# Prefer these survey field names over "first question" (forms like CmF Baseline).
ENUMERATOR_FIELD_NAMES = (
    "assessor_name",
    "enumerator",
    "enumerator_name",
    "enumerator_id",
    "enum_name",
    "enum_id",
    "data_collector",
    "data_collector_name",
    "collector_name",
    "interviewer",
    "interviewer_name",
    "surveyor",
    "surveyor_name",
)

ENUMERATOR_LABEL_HINTS = (
    "enumerator name",
    "enumerator",
    "assessor name",
    "assessor",
    "data collector",
    "data-collector",
    "collector name",
    "interviewer",
    "surveyor",
    "अन्वेषक नाम",
    "डेटा संग्रहकर्ता",
    "संग्रहकर्ता का नाम",
    "गणक",
)

_DATE_LIKE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T\s].*)?$")


def looks_like_date_value(raw: str) -> bool:
    """True for ISO dates/datetimes that must never be treated as an enumerator name."""
    return bool(_DATE_LIKE_RE.match((raw or "").strip()))


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

    def _match(target: str) -> str | None:
        needle = target.strip().lower()
        if not needle:
            return None
        for lang in available:
            lowered = lang.lower()
            if lowered == needle or lowered.startswith(f"{needle} ") or lowered.startswith(
                f"{needle}("
            ):
                return lang
        return None

    if preferred:
        matched = _match(preferred)
        if matched:
            return matched

    matched = _match("english")
    if matched:
        return matched

    settings = (form_definition or {}).get("settings") or {}
    default = settings.get("default_language")
    if isinstance(default, str):
        matched = _match(default)
        if matched:
            return matched

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


def _survey_items(form_definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    survey = (form_definition or {}).get("survey")
    if not isinstance(survey, list):
        return []
    return [item for item in survey if isinstance(item, dict)]


def _question_list_name(item: dict[str, Any]) -> str | None:
    list_name = item.get("select_from_list_name")
    return list_name if isinstance(list_name, str) else None


def _all_label_text(item: dict[str, Any]) -> str:
    """Join every label translation so hint matching is language-agnostic."""
    raw = item.get("label")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return " ".join(str(part) for part in raw if part)
    if isinstance(raw, dict):
        return " ".join(str(part) for part in raw.values() if part)
    return ""


def first_survey_question(
    form_definition: dict[str, Any] | None,
) -> tuple[str, str | None] | None:
    for item in _survey_items(form_definition):
        name = item.get("name")
        qtype = item.get("type")
        if not isinstance(name, str) or not isinstance(qtype, str):
            continue
        if qtype in ENUMERATOR_SKIP_TYPES:
            continue
        return name, _question_list_name(item)
    return None


def find_enumerator_question(
    form_definition: dict[str, Any] | None,
) -> tuple[str, str | None] | None:
    """Locate the enumerator/assessor field for a form.

    Prefer explicit field names (e.g. ``assessor_name`` on CmF Baseline), then
    label/name hints, then the first non-meta survey question.
    """
    items = _survey_items(form_definition)
    by_name: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item.get("name")
        qtype = item.get("type")
        if not isinstance(name, str) or not isinstance(qtype, str):
            continue
        if qtype in ENUMERATOR_SKIP_TYPES:
            continue
        by_name.setdefault(name.lower(), item)

    for preferred in ENUMERATOR_FIELD_NAMES:
        item = by_name.get(preferred.lower())
        if item is not None:
            return str(item["name"]), _question_list_name(item)

    for item in items:
        name = item.get("name")
        qtype = item.get("type")
        if not isinstance(name, str) or not isinstance(qtype, str):
            continue
        if qtype in ENUMERATOR_SKIP_TYPES:
            continue
        # Skip free-text notes that mention investigators but aren't identity fields.
        if name.endswith("_note") or "note" in name.lower():
            continue
        haystack = f"{name} {_all_label_text(item)}".lower()
        if any(hint in haystack for hint in ENUMERATOR_LABEL_HINTS):
            return name, _question_list_name(item)

    return first_survey_question(form_definition)


def clean_enumerator_name(raw: str) -> str:
    """Collapse whitespace/underscores and Title-Case Latin tokens."""
    text = " ".join(str(raw).replace("_", " ").replace(",", " ").split()).strip()
    if not text:
        return ""
    parts: list[str] = []
    for token in text.split():
        if token.isascii() and any(ch.isalpha() for ch in token):
            # Title-case Latin pieces (CHIRAYU → Chirayu, sevak → Sevak).
            parts.append(token[:1].upper() + token[1:].lower())
        else:
            parts.append(token)
    return " ".join(parts)


def match_key_for_enumerator(name: str) -> str:
    """Case-insensitive key with spaces removed (joins Devanagari spaced variants)."""
    normalized = clean_enumerator_name(name)
    return "".join(normalized.casefold().split())


def _enumerator_tokens(name: str) -> list[str]:
    return clean_enumerator_name(name).casefold().split()


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


# Explicit typo / spelling aliases → preferred display form (after clean).
ENUMERATOR_DISPLAY_ALIASES: dict[str, str] = {
    match_key_for_enumerator("Laxman lal mant"): "Laxman Lal Manat",
    match_key_for_enumerator("लखाराम"): "लखा राम",
    match_key_for_enumerator("Lakha Ram"): "लखा राम",
}


def build_enumerator_canonical_map(
    names: list[str],
    *,
    counts: dict[str, int] | None = None,
) -> dict[str, str]:
    """Map raw enumerator strings to a single display name per person.

    Merges:
    - Case / spacing variants (CHIRAYU SEVAK ↔ Chirayu Sevak, लखाराम ↔ लखा राम)
    - Unique shorter forms of a longer name (Chirayu → Chirayu Sevak) when unambiguous
    - Near-typos on the match key (edit distance 1) when the first token matches
    - Explicit aliases in ENUMERATOR_DISPLAY_ALIASES
    """
    cleaned_by_raw: dict[str, str] = {}
    for raw in names:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        cleaned_by_raw[text] = clean_enumerator_name(text) or text

    if not cleaned_by_raw:
        return {}

    freq: dict[str, int] = defaultdict(int)
    for raw, cleaned in cleaned_by_raw.items():
        weight = (counts or {}).get(raw, 1)
        freq[cleaned] += max(1, int(weight))

    # Union-find over cleaned display forms.
    parent: dict[str, str] = {name: name for name in freq}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        parent[rb] = ra

    # 1) Explicit aliases + identical match keys.
    by_key: dict[str, list[str]] = defaultdict(list)
    for name in freq:
        key = match_key_for_enumerator(name)
        alias = ENUMERATOR_DISPLAY_ALIASES.get(key)
        if alias:
            alias_clean = clean_enumerator_name(alias)
            if alias_clean not in parent:
                parent[alias_clean] = alias_clean
                freq[alias_clean] = freq.get(alias_clean, 0)
            union(name, alias_clean)
            key = match_key_for_enumerator(alias_clean)
        by_key[key].append(name)
    for group in by_key.values():
        for other in group[1:]:
            union(group[0], other)

    cleaned_names = list(freq.keys())

    # 2) Unique token-prefix merge (Chirayu → Chirayu Sevak only if one extension).
    for short in cleaned_names:
        short_tokens = _enumerator_tokens(short)
        if not short_tokens:
            continue
        extensions = [
            long
            for long in cleaned_names
            if long != short
            and (long_tokens := _enumerator_tokens(long))
            and len(long_tokens) > len(short_tokens)
            and long_tokens[: len(short_tokens)] == short_tokens
        ]
        if len(extensions) == 1:
            union(short, extensions[0])

    # 3) Near-typos: same first token, edit distance 1 on compact key.
    for i, left in enumerate(cleaned_names):
        left_tokens = _enumerator_tokens(left)
        if not left_tokens:
            continue
        left_key = match_key_for_enumerator(left)
        if len(left_key) < 8:
            continue
        for right in cleaned_names[i + 1 :]:
            right_tokens = _enumerator_tokens(right)
            if not right_tokens or left_tokens[0] != right_tokens[0]:
                continue
            right_key = match_key_for_enumerator(right)
            if abs(len(left_key) - len(right_key)) > 1:
                continue
            if _levenshtein(left_key, right_key) == 1:
                union(left, right)

    # Pick canonical display per component: prefer alias target, then frequency, then length.
    members: dict[str, list[str]] = defaultdict(list)
    for name in freq:
        members[find(name)].append(name)

    canonical_for_cleaned: dict[str, str] = {}
    for group in members.values():
        preferred = max(
            group,
            key=lambda n: (
                len(_enumerator_tokens(n)),
                freq.get(n, 0),
                len(n),
            ),
        )
        # Prefer explicit alias display when present in the component.
        for name in group:
            key = match_key_for_enumerator(name)
            if key in ENUMERATOR_DISPLAY_ALIASES:
                preferred = clean_enumerator_name(ENUMERATOR_DISPLAY_ALIASES[key])
                break
        for name in group:
            canonical_for_cleaned[name] = preferred

    return {
        raw: canonical_for_cleaned.get(cleaned, cleaned)
        for raw, cleaned in cleaned_by_raw.items()
    }


def _usable_enumerator_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = clean_enumerator_name(str(raw))
    if not text or looks_like_date_value(text):
        return None
    return text


def _value_from_question(
    data: dict[str, Any],
    form_definition: dict[str, Any] | None,
    name: str,
    list_name: str | None,
) -> str | None:
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
                return _usable_enumerator_name(label)
    return _usable_enumerator_name(text)


def _enumerator_from_payload(
    data: dict[str, Any],
    form_definition: dict[str, Any] | None = None,
) -> str | None:
    """Read common enumerator keys directly from the submission payload."""
    for preferred in ENUMERATOR_FIELD_NAMES:
        raw = _find_field_value(data, preferred)
        if raw is None:
            continue
        # Prefer choice labels when the survey declares a matching select list.
        question = None
        for item in _survey_items(form_definition):
            if str(item.get("name") or "").lower() == preferred.lower():
                question = item
                break
        if question is not None:
            value = _value_from_question(
                data, form_definition, preferred, _question_list_name(question)
            )
            if value:
                return value
        value = _usable_enumerator_name(str(raw))
        if value:
            return value

    # Deployed XPath-style keys (e.g. identification/enumerator) when schema name differs.
    for key, raw in data.items():
        if not isinstance(key, str) or raw is None:
            continue
        leaf = key.split("/")[-1].lower()
        if leaf not in {n.lower() for n in ENUMERATOR_FIELD_NAMES} and leaf not in {
            "enumerator",
            "assessor_name",
        }:
            continue
        value = _usable_enumerator_name(str(raw))
        if value:
            return value
    return None


def extract_enumerator_name(
    data: dict[str, Any],
    form_definition: dict[str, Any] | None,
) -> str | None:
    question = find_enumerator_question(form_definition)
    if question:
        name, list_name = question
        value = _value_from_question(data, form_definition, name, list_name)
        if value:
            return value

    # Schema field missing/empty, or deploy key differs (CmF Register uses
    # identification/enumerator while survey still names the question DC).
    return _enumerator_from_payload(data, form_definition)


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
