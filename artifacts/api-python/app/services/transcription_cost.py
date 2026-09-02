"""Shared transcription cost estimation helpers."""

from __future__ import annotations

import math

from app.db.models import AppSettings


def estimate_amount(
    settings_row: AppSettings,
    *,
    duration_seconds: float,
    provider_amount: float | None = None,
) -> tuple[float, str]:
    currency = settings_row.transcription_currency or "INR"
    if provider_amount is not None:
        return provider_amount, currency
    rate = float(settings_row.transcription_rate_per_minute or 0.0)
    if rate <= 0 or duration_seconds <= 0:
        return 0.0, currency
    minutes = math.ceil(duration_seconds / 60.0)
    return minutes * rate, currency
