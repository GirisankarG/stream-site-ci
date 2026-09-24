"""Drift between what CI built from git and what the live site serves."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import drift_check as D                                           # noqa: E402

E = lambda *s: [{"t": x, "s": x} for x in s]


def test_identical_indexes_are_silent():
    """Measured: built from the deployed code, 13,631 and 13,631 match exactly."""
    assert D.judge(E("a", "b"), E("b", "a"))[0] == []


def test_deployed_from_unpushed_work_fires_and_says_push():
    """The 2026-09-24 state: 98 titles live that no pushed commit builds."""
    probs, m = D.judge(E("a"), E("a", "neagley-2026"))
    assert m["live_not_pushed"] == 1
    assert any("unpushed work" in p and "neagley-2026" in p and "Push" in p for p in probs)


def test_pushed_not_deployed_fires():
    probs, m = D.judge(E("a", "new-one"), E("a"))
    assert m["pushed_not_live"] == 1 and any("not deployed" in p for p in probs)


def test_empty_index_is_unmeasured_not_in_sync():
    """Two empty sets are 'equal'. That must never read as no drift."""
    probs, _ = D.judge([], [])
    assert probs and "could not be measured" in probs[0]
