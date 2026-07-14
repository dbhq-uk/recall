import tomllib
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "eval" / "fixture"
GOLDEN = Path(__file__).parent.parent / "eval" / "golden.toml"

# Words we do not count as "leakage" when checking a semantic query.
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "we", "i", "you", "how", "what",
    "why", "when", "where", "do", "does", "did", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "for", "with", "at", "by", "from", "up", "out", "it",
    "this", "that", "our", "my", "can", "could", "should", "would", "get", "got",
    "use", "used", "using", "make", "made", "so", "as", "not", "no", "any", "all",
}


def _words(text: str) -> set[str]:
    return {
        w.strip(".,:;!?()[]{}\"'`").lower()
        for w in text.split()
    } - STOPWORDS - {""}


@pytest.fixture(scope="module")
def golden() -> list[dict]:
    return tomllib.loads(GOLDEN.read_text())["query"]


def test_golden_set_has_forty_queries(golden):
    assert len(golden) == 40


def test_golden_set_has_the_designed_mix_of_kinds(golden):
    kinds = [q["kind"] for q in golden]
    assert kinds.count("semantic") == 15
    assert kinds.count("lexical") == 15
    assert kinds.count("hybrid") == 10


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
