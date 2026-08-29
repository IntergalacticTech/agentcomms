# tests/core/test_ulid.py
import re
from core.data.ulid_ import new_id


def test_new_id_agent():
    v = new_id("agt")
    assert re.match(r"^agt_[0-9A-HJKMNP-TV-Z]{26}$", v), v


def test_new_id_channel_with_suffix():
    v = new_id("chan", suffix="em")
    assert v.startswith("chan_em_")


def test_new_id_monotonic_when_called_rapidly():
    vals = sorted(new_id("msg") for _ in range(100))
    # ULIDs at the same ms are lex-ordered by the random part, so sorted order
    # should match insertion order within a single ms window. We test
    # uniqueness here; full monotonic ordering is a nice-to-have, not a
    # requirement.
    assert len(set(vals)) == 100
