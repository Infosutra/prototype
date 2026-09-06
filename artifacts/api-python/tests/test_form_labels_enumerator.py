from app.services.form_labels import (
    build_enumerator_canonical_map,
    clean_enumerator_name,
    extract_enumerator_name,
    find_enumerator_question,
)


def test_prefers_assessor_name_over_today_meta():
    form_definition = {
        "translations": ["Hindi", "English"],
        "survey": [
            {"type": "today", "name": "today"},
            {
                "type": "text",
                "name": "assessor_name",
                "label": ["डेटा कलेक्टर का नाम", "Assessor name and code"],
            },
            {"type": "date", "name": "assessment_date", "label": ["तिथि", "Date"]},
        ],
    }
    assert find_enumerator_question(form_definition) == ("assessor_name", None)
    assert (
        extract_enumerator_name({"assessor_name": "Ravi_Kumar"}, form_definition)
        == "Ravi Kumar"
    )


def test_falls_back_to_first_question_when_no_named_field():
    form_definition = {
        "survey": [
            {"type": "start", "name": "start"},
            {
                "type": "select_one",
                "name": "Q1",
                "label": "Enumerator",
                "select_from_list_name": "enumerators",
            },
        ],
        "choices": [
            {"list_name": "enumerators", "name": "e1", "label": "Ada Lovelace"},
        ],
    }
    assert find_enumerator_question(form_definition) == ("Q1", "enumerators")
    assert extract_enumerator_name({"Q1": "e1"}, form_definition) == "Ada Lovelace"


def test_matches_enumerator_field_name():
    form_definition = {
        "survey": [
            {"type": "today", "name": "today"},
            {"type": "text", "name": "enumerator", "label": "गणक"},
        ],
    }
    assert extract_enumerator_name({"enumerator": "Priya"}, form_definition) == "Priya"


def test_payload_only_common_field_when_no_survey():
    assert extract_enumerator_name({"assessor_name": "Sam"}, None) == "Sam"


def test_matches_data_collector_label_not_investigator_note():
    form_definition = {
        "translations": ["Hindi (hi)", "default", "None", "English (en)"],
        "survey": [
            {"type": "today", "name": "today"},
            {
                "type": "select_one",
                "name": "DC",
                "label": ["डेटा संग्रहकर्ता का नाम", None, None, "Data Collector Name"],
                "select_from_list_name": "collectors",
            },
            {
                "type": "text",
                "name": "investigator_note",
                "label": ["अन्वेषक का टिप्पणी:", None, None, "NOTE OF THE INVESTIGATOR:"],
            },
        ],
        "choices": [
            {
                "list_name": "collectors",
                "name": "c1",
                "label": ["रावि", None, None, "Ravi"],
            },
        ],
    }
    assert find_enumerator_question(form_definition) == ("DC", "collectors")
    assert extract_enumerator_name({"DC": "c1"}, form_definition) == "Ravi"


def test_rejects_date_like_first_question_value():
    form_definition = {
        "survey": [
            {"type": "text", "name": "odd", "label": "Odd"},
            {"type": "text", "name": "enumerator", "label": "Enumerator"},
        ],
    }
    # Prefer enumerator field over a date-looking odd field when using payload fallback
    assert (
        extract_enumerator_name(
            {"odd": "2026-09-03", "enumerator": "Ada"}, form_definition
        )
        == "Ada"
    )


def test_register_style_xpath_enumerator_when_schema_field_missing():
    form_definition = {
        "translations": ["Hindi (hi)", "default", "None", "English (en)"],
        "survey": [
            {"type": "today", "name": "today"},
            {
                "type": "select_one",
                "name": "DC",
                "label": ["डेटा संग्रहकर्ता का नाम", None, None, "Data Collector Name"],
                "select_from_list_name": "DC",
            },
        ],
        "choices": [
            {
                "list_name": "DC",
                "name": "Lakha Ram",
                "label": ["लाखा राम", None, None, "Lakha Ram"],
            },
        ],
    }
    # Deployed payloads use identification/enumerator instead of DC.
    assert (
        extract_enumerator_name(
            {"today": "2026-09-03", "identification/enumerator": "Nivedita"},
            form_definition,
        )
        == "Nivedita"
    )


def test_clean_enumerator_name_title_cases_latin():
    assert clean_enumerator_name("CHIRAYU SEVAK") == "Chirayu Sevak"
    assert clean_enumerator_name("Chirayu sevak") == "Chirayu Sevak"
    assert clean_enumerator_name("लखा राम") == "लखा राम"


def test_canonical_map_merges_case_and_unique_short_forms():
    names = [
        "CHIRAYU SEVAK",
        "Chirayu Sevak",
        "Chirayu sevak",
        "Chirayu",
        "chirayu",
        "Piyush",
        "Piyush Prajapat",
        "BALRAJ BAMANIYA",
        "Balraj kumar",
        "Balraj",
        "Laxman lal mant",
        "Laxman lal manat",
        "लखाराम",
        "लखा राम",
    ]
    counts = {n: 1 for n in names}
    counts["Chirayu Sevak"] = 5
    counts["Piyush Prajapat"] = 10
    counts["BALRAJ BAMANIYA"] = 8
    counts["Balraj kumar"] = 2
    mapping = build_enumerator_canonical_map(names, counts=counts)

    assert mapping["CHIRAYU SEVAK"] == "Chirayu Sevak"
    assert mapping["Chirayu"] == "Chirayu Sevak"
    assert mapping["Piyush"] == "Piyush Prajapat"
    assert mapping["BALRAJ BAMANIYA"] == "Balraj Bamaniya"
    assert mapping["Balraj kumar"] == "Balraj Kumar"
    assert mapping["Balraj"] == "Balraj"
    assert mapping["Laxman lal mant"] == "Laxman Lal Manat"
    assert mapping["लखाराम"] == "लखा राम"
    assert mapping["लखा राम"] == "लखा राम"
