from datetime import UTC, datetime

import pytest

from xiaolv.domain.conversation.reply_validity import evaluate_reply_validity


def test_reply_is_rejected_at_exact_expiry():
    instant = datetime(2026, 9, 29, 8, tzinfo=UTC)
    decision = evaluate_reply_validity(instant, 3, 3, instant)
    assert (decision.allowed, decision.reason) == (False, "expired")


def test_current_reply_is_allowed_before_expiry():
    expiry = datetime(2026, 9, 29, 8, 1, tzinfo=UTC)
    now = datetime(2026, 9, 29, 8, tzinfo=UTC)
    decision = evaluate_reply_validity(expiry, 3, 3, now)
    assert (decision.allowed, decision.reason) == (True, "valid")


def test_reply_from_old_epoch_is_rejected():
    expiry = datetime(2026, 9, 29, 8, 1, tzinfo=UTC)
    now = datetime(2026, 9, 29, 8, tzinfo=UTC)
    decision = evaluate_reply_validity(expiry, 2, 3, now)
    assert (decision.allowed, decision.reason) == (False, "superseded")


def test_expired_reason_takes_priority_over_old_epoch():
    expiry = datetime(2026, 9, 29, 8, tzinfo=UTC)
    now = datetime(2026, 9, 29, 8, 30, tzinfo=UTC)
    decision = evaluate_reply_validity(expiry, 2, 3, now)
    assert (decision.allowed, decision.reason) == (False, "expired")


def test_equal_instants_with_different_offsets_are_expired():
    expiry = datetime.fromisoformat("2026-09-29T16:00:00+08:00")
    now = datetime.fromisoformat("2026-09-29T08:00:00+00:00")
    decision = evaluate_reply_validity(expiry, 3, 3, now)
    assert (decision.allowed, decision.reason) == (False, "expired")


@pytest.mark.parametrize("naive_field", ["expires_at", "now", "both"])
def test_naive_timestamps_are_rejected(naive_field):
    expiry = datetime(2026, 9, 29, 8, 1, tzinfo=UTC)
    now = datetime(2026, 9, 29, 8, tzinfo=UTC)
    if naive_field in ("expires_at", "both"):
        expiry = expiry.replace(tzinfo=None)
    if naive_field in ("now", "both"):
        now = now.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_reply_validity(expiry, 3, 3, now)


def test_repeated_local_hour_compares_absolute_instants():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    expiry = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    now = datetime(2026, 11, 1, 1, 45, tzinfo=zone, fold=0)
    decision = evaluate_reply_validity(expiry, 3, 3, now)
    assert (decision.allowed, decision.reason) == (True, "valid")
