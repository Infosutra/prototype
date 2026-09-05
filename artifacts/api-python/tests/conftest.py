"""Shared pytest fixtures for the Infosutra API test suite."""

from __future__ import annotations

import pytest
from freezegun import freeze_time

# Matches the golden report execution date in Asia/Kolkata (study timezone).
FROZEN_NOW = "2026-03-15T10:00:00+05:30"


@pytest.fixture
def frozen_now():
    """Freeze wall-clock time for deterministic report metadata (generatedAt*)."""
    with freeze_time(FROZEN_NOW):
        yield
