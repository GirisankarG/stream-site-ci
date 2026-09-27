"""Sitemap completeness as an identity: built - noindex == sitemap."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import identity_check as I                                        # noqa: E402


def test_the_deployed_build_holds():
    """Measured 2026-09-27: 13,631 - 5,433 = 8,198."""
    assert I.judge(13631, 5433, 8198) == []


def test_sitemap_that_dropped_indexable_pages_fires():
    probs = I.judge(13631, 5433, 7348)
    assert probs and "identity broken" in probs[0] and "-850" in probs[0]


def test_a_legitimate_host_death_still_holds():
    """850 titles fall below the bar: noindex rises and the sitemap falls together."""
    assert I.judge(13631, 5433 + 850, 8198 - 850) == []


def test_empty_build_is_measured_nothing():
    assert I.judge(0, 0, 0)


def test_counts_real_files(tmp_path):
    w = tmp_path / "watch"; w.mkdir()
    (w / "a.html").write_text('<meta name="robots" content="index,follow">')
    (w / "b.html").write_text('<meta name="robots" content="noindex,follow">')
    (tmp_path / "sitemap.xml").write_text("<loc>https://flixshows.me/watch/a</loc>")
    sys.argv = ["identity_check.py", "--dist", str(tmp_path), "--summary", str(tmp_path / "s.json")]
    assert I.main() == 0
