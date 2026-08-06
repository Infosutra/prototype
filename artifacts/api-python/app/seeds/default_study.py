"""Default demo study constants and triangulation view seed loaders.

All study-specific vocabulary for the seeded AKF/Sightsavers baseline lives here
so the rest of the app stays study-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_STUDY_ID = "study-sightsavers-2030"
DEFAULT_STUDY_NAME = "Sightsavers 2030"
DEFAULT_STUDY_DESCRIPTION = (
    "AKF Schools2030 Inclusive Education Baseline, Bihar — "
    "T1 Facility/School · T2 Teacher & AWW KAP · T3 Parents/Caregivers"
)
DEFAULT_STUDY_START_DATE = "2026-07-20"
DEFAULT_STUDY_TIMEZONE = "Asia/Kolkata"

# Known form UIDs for the seeded study (Kobo asset UIDs).
DEFAULT_STUDY_FORMS = [
    {
        "toolCode": "T1",
        "projectUid": "ajHnaDiKywwDknGB3L2nLC",
        "label": "Facility / School Assessment",
    },
    {
        "toolCode": "T2",
        "projectUid": "a5qKLPgxnHTaYbrDWeeg9v",
        "label": "Teachers & Anganwadi Workers",
    },
    {
        "toolCode": "T3",
        "projectUid": "aN5bufzTGmh9SibWSDZBr8",
        "label": "Parents & Caregivers",
    },
]
# Placeholder planned counts from the DQA report sample — editable in UI.
DEFAULT_STUDY_TARGETS = {"T1": 440, "T2": 960, "T3": 880}

_TRIANGULATION_DIR = Path(__file__).resolve().parent / "triangulation"


def load_triangulation_seed_definitions() -> list[dict[str, Any]]:
    """Load TR-* YAML definitions shipped with the default study seed."""
    if not _TRIANGULATION_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(_TRIANGULATION_DIR.glob("*.yml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict) and data.get("code"):
            out.append(data)
    return out
