from app.eval.cases import ExpectedHit
from app.eval.metrics import Hit, first_hit_rank, hit_at, overlaps, reciprocal_rank, summarize


def _hit(path="a.pdf", start=10, end=12, score=0.5):
    return Hit(source_path=path, page_start=start, page_end=end, score=score)


def _exp(path="a.pdf", pages=(11, 15)):
    return ExpectedHit(source_path=path, pages=pages)


def test_overlap_on_shared_page():
    assert overlaps(_hit(start=10, end=12), _exp(pages=(12, 20)))


def test_no_overlap_when_ranges_touch_but_do_not_share_a_page():
    assert not overlaps(_hit(start=10, end=12), _exp(pages=(13, 20)))


def test_no_overlap_across_documents():
    assert not overlaps(_hit(path="a.pdf"), _exp(path="b.pdf", pages=(10, 12)))


def test_first_hit_rank_is_one_based():
    hits = [_hit(start=1, end=2), _hit(start=11, end=11)]

    assert first_hit_rank(hits, [_exp(pages=(11, 15))]) == 2


def test_first_hit_rank_none_when_nothing_matches():
    assert first_hit_rank([_hit(start=1, end=2)], [_exp(pages=(11, 15))]) is None


def test_any_expected_item_counts():
    hits = [_hit(path="slides.pdf", start=3, end=3)]
    expected = [_exp(path="book.pdf", pages=(1, 9)), _exp(path="slides.pdf", pages=(3, 3))]

    assert first_hit_rank(hits, expected) == 1


def test_reciprocal_rank():
    assert reciprocal_rank(1) == 1.0
    assert reciprocal_rank(4) == 0.25
    assert reciprocal_rank(None) == 0.0


def test_hit_at_k():
    assert hit_at(3, 3)
    assert not hit_at(4, 3)
    assert not hit_at(None, 8)


def test_summarize_averages_over_cases():
    summary = summarize([1, 3, None, 2], ks=(1, 3))

    assert summary["hit@1"] == 0.25
    assert summary["hit@3"] == 0.75
    assert abs(summary["mrr"] - (1 + 1 / 3 + 0 + 0.5) / 4) < 1e-9


def test_summarize_of_nothing_is_zero_not_a_crash():
    assert summarize([], ks=(1,)) == {"hit@1": 0.0, "mrr": 0.0}
