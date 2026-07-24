import tomllib
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "eval" / "fixture"
GOLDEN = Path(__file__).parent.parent / "eval" / "golden.toml"

# Words we do not count as "leakage" when checking a semantic query.
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "we",
    "i",
    "you",
    "how",
    "what",
    "why",
    "when",
    "where",
    "do",
    "does",
    "did",
    "is",
    "are",
    "was",
    "were",
    "be",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "at",
    "by",
    "from",
    "up",
    "out",
    "it",
    "this",
    "that",
    "our",
    "my",
    "can",
    "could",
    "should",
    "would",
    "get",
    "got",
    "use",
    "used",
    "using",
    "make",
    "made",
    "so",
    "as",
    "not",
    "no",
    "any",
    "all",
}


def _words(text: str) -> set[str]:
    return {w.strip(".,:;!?()[]{}\"'`").lower() for w in text.split()} - STOPWORDS - {""}


@pytest.fixture(scope="module")
def golden() -> list[dict]:
    return tomllib.loads(GOLDEN.read_text())["query"]


def test_golden_set_has_the_expected_size(golden):
    # 40 original + 4 heading-only lexical probes (q041-q044).
    assert len(golden) == 44


def test_golden_set_has_the_designed_mix_of_kinds(golden):
    kinds = [q["kind"] for q in golden]
    assert kinds.count("semantic") == 15
    # 15 original lexical + 4 heading-only lexical probes.
    assert kinds.count("lexical") == 19
    assert kinds.count("hybrid") == 10


# The heading-only lexical probes and the codeword each one turns on. The
# codeword must live ONLY in a heading of the target: absent from the chunked
# body (so the lexical half can see it solely via search_text), present in the
# raw file exactly once, on an ATX heading line.
_HEADING_ONLY_PROBES = {
    "q041": "FROSTGATE_PIVOT",
    "q042": "PALEGATE_SWEEP",
    "q043": "EMBERWATCH",
    "q044": "AMPGATE_CHECK",
}


def test_heading_only_probes_keep_their_codeword_out_of_the_body(golden):
    """These four queries are the fixture's regression guard for the
    dense/lexical asymmetry fix (search_text folds the heading into the lexical
    field). The guard is only meaningful while the codeword stays heading-only:
    if it leaks into the body, `content` alone would match it and the probe
    would pass even with the fix reverted. Enforce heading-only-ness."""
    by_id = {q["id"]: q for q in golden}
    for qid, codeword in _HEADING_ONLY_PROBES.items():
        q = by_id[qid]
        assert q["kind"] == "lexical"
        assert codeword in q["text"], f"{qid} must ask about {codeword}"
        (rel,) = q["relevant"]
        lines = (FIXTURE / rel).read_text().splitlines()
        hits = [ln for ln in lines if codeword in ln]
        assert len(hits) == 1, f"{codeword} must appear exactly once in {rel}, on its heading"
        assert hits[0].lstrip().startswith("#"), (
            f"{codeword} must be on an ATX heading line in {rel}, not in the body — "
            f"otherwise the lexical `content` column would match it and the probe would "
            f"pass even with the search_text enrichment reverted"
        )


def test_heading_only_probes_share_no_body_word_with_their_query(golden):
    """The codeword must be the ONLY thing tying the query to the target.

    If the query also shares an ordinary content word with the body (e.g. the
    query says 'failover drill' and so does the prose), then `content`-only BM25
    matches on that word and ranks the file correctly WITHOUT ever needing the
    heading — so the probe passes even with search_text reverted, measuring
    nothing. The first draft of these probes had exactly that bug. Enforce that
    the query and the *chunked body* (heading excluded) share no significant
    word: the codeword, which lives only in the heading trail (-> context ->
    search_text), is then the sole lexical anchor, and a content-only lexical
    half genuinely cannot find the target."""
    from recall.chunkers import chunk_file

    by_id = {q["id"]: q for q in golden}
    for qid in _HEADING_ONLY_PROBES:
        q = by_id[qid]
        (rel,) = q["relevant"]
        chunks = chunk_file((FIXTURE / rel).read_text(), source="fixture", rel_path=rel, file_sha="s")
        body_words = _words(" ".join(c.content for c in chunks))
        overlap = _words(q["text"]) & body_words
        assert overlap == set(), (
            f"{qid} shares {sorted(overlap)} with the body of {rel}; a content-only "
            f"lexical half could match on those, so the probe no longer isolates the "
            f"heading-enrichment. Reword the query to lean only on the codeword."
        )


def test_query_ids_are_unique(golden):
    ids = [q["id"] for q in golden]
    assert len(ids) == len(set(ids))


def test_every_relevant_path_actually_exists(golden):
    for q in golden:
        assert q["relevant"], f"{q['id']} has no relevant documents"
        for rel in q["relevant"]:
            assert (FIXTURE / rel).is_file(), f"{q['id']} points at missing file {rel}"


def test_SEMANTIC_QUERIES_DO_NOT_LEAK_THEIR_ANSWERS(golden):
    """The anti-contamination guard.

    The design warns that public benchmarks flatter retrieval systems because
    their queries are derived from the target text verbatim. A "semantic" query
    that reuses the target's content words is not testing semantic retrieval at
    all — it is testing string matching, and it will make our numbers a lie.

    So: a semantic query may share at most ONE significant word with its target.
    """
    for q in golden:
        if q["kind"] != "semantic":
            continue
        qwords = _words(q["text"])
        for rel in q["relevant"]:
            target = _words((FIXTURE / rel).read_text())
            overlap = qwords & target
            assert len(overlap) <= 1, (
                f"{q['id']} is a 'semantic' query but shares {sorted(overlap)} with "
                f"{rel}. Rewrite it to ask the question in words the answer does not use."
            )


def test_corpus_is_big_enough_for_recall_at_10_to_mean_anything(golden):
    md = list(FIXTURE.rglob("*.md"))
    assert len(md) >= 35, f"only {len(md)} markdown files; need enough distractors"
    total_chars = sum(f.stat().st_size for f in md)
    assert total_chars > 120_000, "corpus too thin to produce 250+ chunks"


def test_fixture_declares_itself_as_a_source(golden):
    assert (FIXTURE / ".recall.toml").is_file()
