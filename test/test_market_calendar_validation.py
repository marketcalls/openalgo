"""Validation tests for market calendar service date inputs."""

import pytest

from services import market_calendar_service


@pytest.mark.parametrize("invalid_date", [None, 123, "", "not-a-date"])
@pytest.mark.parametrize(
    "service", [market_calendar_service.get_timings, market_calendar_service.check_holiday]
)
def test_calendar_service_rejects_invalid_date_values(service, invalid_date):
    success, response, status_code = service(invalid_date)

    assert success is False
    assert status_code == 400
    assert response == {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD"}


def test_get_timings_accepts_valid_iso_date(monkeypatch):
    monkeypatch.setattr(market_calendar_service, "get_market_timings_for_date", lambda _date: [])

    success, response, status_code = market_calendar_service.get_timings("2026-08-22")

    assert success is True
    assert status_code == 200
    assert response == {"status": "success", "data": []}


def test_check_holiday_accepts_valid_iso_date(monkeypatch):
    monkeypatch.setattr(market_calendar_service, "is_market_holiday", lambda *_args: False)

    success, response, status_code = market_calendar_service.check_holiday("2026-08-22")

    assert success is True
    assert status_code == 200
    assert response["data"]["date"] == "2026-08-22"
