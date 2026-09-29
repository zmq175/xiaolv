import pytest

from xiaolv.storage.postgres_turns import CandidatePolicy


@pytest.mark.parametrize(
    "changes",
    [
        {"merge_seconds": -1},
        {"max_merge_seconds": -1},
        {"ttl_seconds": 0},
        {"queue_age_seconds": 0},
        {"queue_age_seconds": 46},
        {"ttl_seconds": float("inf")},
        {"merge_seconds": float("nan")},
        {"queue_age_seconds": True},
        {"enabled_conversations": {"qq:10000:group:20000"}},
        {"enabled_conversations": frozenset({""})},
    ],
)
def test_candidate_policy_rejects_unsafe_or_mutable_configuration(changes):
    with pytest.raises(ValueError, match="candidate policy"):
        CandidatePolicy(**changes)
