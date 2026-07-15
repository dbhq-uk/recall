"""Fast, pure unit tests for eval/swebench.py.

No network, no git, no database, no Ollama. fetch_instances is tested with an
injected _rows_fetcher so the dataset wiring is proven without ever calling
the real HuggingFace API. prepare_repo, evaluate_instance and main() are the
slow/real path (real git, real store, real embedder) and are deliberately not
exercised here -- see eval/swebench.py's module docstring.
"""

from __future__ import annotations

import pytest

from eval.swebench import (
    SweInstance,
    aggregate,
    chunks_to_ranked_files,
    fetch_instances,
    file_metrics,
    gold_files_from_patch,
)

# ---------------------------------------------------------------------------
# gold_files_from_patch -- the ground truth. Tested against real patch shapes.
# ---------------------------------------------------------------------------


def test_gold_files_single_file_real_patch():
    patch = (
        "diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py\n"
        "--- a/astropy/modeling/separable.py\n"
        "+++ b/astropy/modeling/separable.py\n"
        "@@ -242,7 +242,7 @@ def _cstack(left, right):\n"
        "         cright = _coord_matrix(right, 'right', noutp)\n"
        "     else:\n"
        "         cright = np.zeros((noutp, right.shape[1]))\n"
        "-        cright[-right.shape[0]:, -right.shape[1]:] = 1\n"
        "+        cright[-right.shape[0]:, -right.shape[1]:] = right\n"
        " \n"
        "     return np.hstack([cleft, cright])\n"
    )
    assert gold_files_from_patch(patch) == ["astropy/modeling/separable.py"]


def test_gold_files_multi_file_patch():
    patch = (
        "diff --git a/pkg/a.py b/pkg/a.py\n"
        "--- a/pkg/a.py\n"
        "+++ b/pkg/a.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/pkg/b.py b/pkg/b.py\n"
        "--- a/pkg/b.py\n"
        "+++ b/pkg/b.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-old\n"
        "+new\n"
    )
    assert gold_files_from_patch(patch) == ["pkg/a.py", "pkg/b.py"]


def test_gold_files_new_file_patch():
    patch = (
        "diff --git a/new_file.py b/new_file.py\n"
        "new file mode 100644\n"
        "index 0000000..e69de29\n"
        "--- /dev/null\n"
        "+++ b/new_file.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+import os\n"
        "+print(os)\n"
    )
    assert gold_files_from_patch(patch) == ["new_file.py"]


def test_gold_files_deleted_file_patch():
    patch = (
        "diff --git a/old_file.py b/old_file.py\n"
        "deleted file mode 100644\n"
        "index e69de29..0000000\n"
        "--- a/old_file.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-import os\n"
        "-print(os)\n"
    )
    assert gold_files_from_patch(patch) == ["old_file.py"]


def test_gold_files_rename_patch():
    patch = (
        "diff --git a/pkg/old_name.py b/pkg/new_name.py\n"
        "similarity index 100%\n"
        "rename from pkg/old_name.py\n"
        "rename to pkg/new_name.py\n"
    )
    assert gold_files_from_patch(patch) == ["pkg/new_name.py"]


def test_gold_files_empty_patch_returns_empty_list():
    assert gold_files_from_patch("") == []


# ---------------------------------------------------------------------------
# file_metrics
# ---------------------------------------------------------------------------


def test_file_metrics_gold_found_partway_down():
    metrics = file_metrics(["b.py", "a.py", "c.py"], {"a.py"}, k=10)
    assert metrics["recall_at_k"] == pytest.approx(1.0)
    assert metrics["mrr"] == pytest.approx(0.5)
    assert metrics["precision_at_k"] == pytest.approx(1 / 3)


def test_file_metrics_partial_recall():
    metrics = file_metrics(["a.py", "b.py"], {"a.py", "x.py"}, k=10)
    assert metrics["recall_at_k"] == pytest.approx(0.5)


def test_file_metrics_total_miss():
    metrics = file_metrics(["b.py", "c.py"], {"a.py"}, k=10)
    assert metrics["recall_at_k"] == pytest.approx(0.0)
    assert metrics["mrr"] == pytest.approx(0.0)


def test_file_metrics_f1_is_harmonic_mean_of_precision_and_recall():
    metrics = file_metrics(["a.py", "b.py"], {"a.py"}, k=10)
    # recall = 1/1 = 1.0, precision = 1/2 = 0.5
    expected_f1 = 2 * 1.0 * 0.5 / (1.0 + 0.5)
    assert metrics["f1_at_k"] == pytest.approx(expected_f1)


def test_file_metrics_empty_ranked_files_does_not_crash():
    metrics = file_metrics([], {"a.py"}, k=10)
    assert metrics["recall_at_k"] == pytest.approx(0.0)
    assert metrics["precision_at_k"] == pytest.approx(0.0)
    assert metrics["f1_at_k"] == pytest.approx(0.0)
    assert metrics["mrr"] == pytest.approx(0.0)


def test_file_metrics_empty_gold_does_not_divide_by_zero():
    metrics = file_metrics(["a.py"], set(), k=10)
    assert metrics["recall_at_k"] == pytest.approx(0.0)


def test_file_metrics_respects_k_for_precision_and_recall_but_not_mrr():
    # Gold file is at rank 3, k=2 -- it should not count for recall/precision,
    # but mrr looks at the whole ranking, not just the top k.
    metrics = file_metrics(["b.py", "c.py", "a.py"], {"a.py"}, k=2)
    assert metrics["recall_at_k"] == pytest.approx(0.0)
    assert metrics["precision_at_k"] == pytest.approx(0.0)
    assert metrics["mrr"] == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# chunks_to_ranked_files
# ---------------------------------------------------------------------------


class _FakeHit:
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path


def test_chunks_to_ranked_files_dedups_preserving_order():
    hits = [_FakeHit("a.py"), _FakeHit("b.py"), _FakeHit("a.py"), _FakeHit("c.py")]
    assert chunks_to_ranked_files(hits) == ["a.py", "b.py", "c.py"]


def test_chunks_to_ranked_files_empty_input():
    assert chunks_to_ranked_files([]) == []


# ---------------------------------------------------------------------------
# fetch_instances -- injected _rows_fetcher, no network.
# ---------------------------------------------------------------------------


def _synthetic_rows(offset: int, length: int) -> list[dict]:
    if offset > 0:
        return []
    return [
        {
            "repo": "psf/requests",
            "instance_id": "psf__requests-001",
            "base_commit": "abc123",
            "patch": (
                "diff --git a/requests/models.py b/requests/models.py\n"
                "--- a/requests/models.py\n"
                "+++ b/requests/models.py\n"
                "@@ -1,1 +1,1 @@\n"
                "-old\n"
                "+new\n"
            ),
            "problem_statement": "Something is broken in models.py",
            "difficulty": "<15 min fix",
        },
        {
            "repo": "django/django",
            "instance_id": "django__django-002",
            "base_commit": "def456",
            "patch": (
                "diff --git a/django/core.py b/django/core.py\n"
                "--- a/django/core.py\n"
                "+++ b/django/core.py\n"
                "@@ -1,1 +1,1 @@\n"
                "-old\n"
                "+new\n"
            ),
            "problem_statement": "Something is broken in core.py",
            "difficulty": "15 min - 1 hour",
        },
    ]


def test_fetch_instances_filters_by_repo_and_parses_gold_files():
    instances = fetch_instances(repos=["psf/requests"], _rows_fetcher=_synthetic_rows)
    assert len(instances) == 1
    instance = instances[0]
    assert isinstance(instance, SweInstance)
    assert instance.instance_id == "psf__requests-001"
    assert instance.repo == "psf/requests"
    assert instance.gold_files == ["requests/models.py"]


def test_fetch_instances_respects_limit():
    def rows_of_only_requests(offset: int, length: int) -> list[dict]:
        if offset > 0:
            return []
        return [_synthetic_rows(0, length)[0], _synthetic_rows(0, length)[0]]

    instances = fetch_instances(
        repos=["psf/requests"], limit=1, _rows_fetcher=rows_of_only_requests
    )
    assert len(instances) == 1


def test_fetch_instances_stops_on_empty_page():
    calls = []

    def counting_fetcher(offset: int, length: int) -> list[dict]:
        calls.append(offset)
        return []

    instances = fetch_instances(repos=["psf/requests"], _rows_fetcher=counting_fetcher)
    assert instances == []
    assert calls == [0]


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def _result(difficulty: str, dense_recall: float, lexical_recall: float, hybrid_recall: float):
    def arm(recall: float) -> dict[str, float]:
        return {
            "recall_at_k": recall,
            "precision_at_k": recall,
            "f1_at_k": recall,
            "mrr": recall,
        }

    return {
        "instance_id": "x",
        "repo": "psf/requests",
        "difficulty": difficulty,
        "n_gold": 1,
        "arms": {
            "dense": arm(dense_recall),
            "lexical": arm(lexical_recall),
            "hybrid": arm(hybrid_recall),
        },
    }


def test_aggregate_averages_metrics_across_results():
    results = [
        _result("easy", dense_recall=1.0, lexical_recall=0.0, hybrid_recall=1.0),
        _result("easy", dense_recall=0.0, lexical_recall=1.0, hybrid_recall=1.0),
    ]
    agg = aggregate(results)
    assert agg["overall"]["n"] == 2
    assert agg["overall"]["arms"]["dense"]["recall_at_k"] == pytest.approx(0.5)
    assert agg["overall"]["arms"]["lexical"]["recall_at_k"] == pytest.approx(0.5)
    assert agg["overall"]["arms"]["hybrid"]["recall_at_k"] == pytest.approx(1.0)


def test_aggregate_groups_by_difficulty():
    results = [
        _result("easy", dense_recall=1.0, lexical_recall=1.0, hybrid_recall=1.0),
        _result("hard", dense_recall=0.0, lexical_recall=0.0, hybrid_recall=0.0),
    ]
    agg = aggregate(results)
    assert agg["by_difficulty"]["easy"]["n"] == 1
    assert agg["by_difficulty"]["easy"]["arms"]["hybrid"]["recall_at_k"] == pytest.approx(1.0)
    assert agg["by_difficulty"]["hard"]["n"] == 1
    assert agg["by_difficulty"]["hard"]["arms"]["hybrid"]["recall_at_k"] == pytest.approx(0.0)


def test_aggregate_empty_results_does_not_crash():
    agg = aggregate([])
    assert agg["overall"]["n"] == 0
    assert agg["overall"]["arms"]["hybrid"]["recall_at_k"] == pytest.approx(0.0)
    assert agg["by_difficulty"] == {}
