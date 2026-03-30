"""Unit tests for boost_library_usage_dashboard.analyzer core logic."""

from pathlib import Path
from unittest.mock import patch
import tempfile

from boost_library_usage_dashboard.analyzer import BoostUsageDashboardAnalyzer


def _make_analyzer() -> BoostUsageDashboardAnalyzer:
    analyzer = BoostUsageDashboardAnalyzer.__new__(BoostUsageDashboardAnalyzer)
    analyzer.output_dir = Path(tempfile.gettempdir()) / "boost-dashboard-test-output"
    analyzer.version_name_list = ["1.50.0", "1.51.0", "1.52.0", "1.53.0", "1.54.0"]
    analyzer.repo_info = []
    analyzer.library_info = []
    analyzer.repo_info_dict = {}
    analyzer.stars_min_threshold = 10
    return analyzer


def test_calculate_trend_metrics_empty_data_returns_defaults():
    analyzer = _make_analyzer()
    result = analyzer.calculate_trend_metrics([], recent_year_threshold=2020)
    assert result["total_usage"] == 0
    assert result["recent_usage"] == 0
    assert result["past_usage"] == 0
    assert result["activity_score"] == -10.0


def test_calculate_trend_metrics_zero_usage_returns_defaults():
    analyzer = _make_analyzer()
    year_data = [(2022, {"created_count": 0, "last_commit_count": 0})]
    result = analyzer.calculate_trend_metrics(year_data, recent_year_threshold=2020)
    assert result["total_usage"] == 0
    assert result["activity_score"] == -10.0


def test_calculate_trend_metrics_nonzero_usage_has_numeric_score():
    analyzer = _make_analyzer()
    year_data = [
        (2020, {"created_count": 2, "last_commit_count": 0}),
        (2021, {"created_count": 4, "last_commit_count": 0}),
        (2022, {"created_count": 6, "last_commit_count": 0}),
    ]
    result = analyzer.calculate_trend_metrics(year_data, recent_year_threshold=2021)
    assert result["total_usage"] >= 0
    assert isinstance(result["activity_score"], float)


def test_normalize_and_moving_version_boundaries():
    analyzer = _make_analyzer()
    assert analyzer._normalize_and_moving_version("", 1) is None
    assert analyzer._normalize_and_moving_version("9.99.0", 1) == "9.99.0"
    assert analyzer._normalize_and_moving_version("1.50.0", -1) is None
    assert analyzer._normalize_and_moving_version("1.54.0", 1) is None
    assert analyzer._normalize_and_moving_version("1.53.0", -1) == "1.52.0"
    assert analyzer._normalize_and_moving_version("1.53.0", 1) == "1.54.0"


def test_find_all_transitive_dependencies_handles_cycles_and_self():
    analyzer = _make_analyzer()
    graph = {
        1: {100: [1, 2]},  # self and dep 2
        2: {100: [3]},
        3: {100: [2]},  # cycle
    }
    out = analyzer._find_all_transitive_dependencies(1, 100, graph)
    assert out == {2: 1, 3: 2}


def test_find_all_transitive_dependencies_no_graph_or_version():
    analyzer = _make_analyzer()
    assert analyzer._find_all_transitive_dependencies(1, 100, {}) == {}
    assert analyzer._find_all_transitive_dependencies(1, 100, {1: {}}) == {}


def test_filter_and_sort_libraries_with_conditions_and_limit():
    analyzer = _make_analyzer()
    analyzer.library_info = [
        {"name": "a", "repo_count": 0, "activity_score": -10, "total_usage": 0},
        {"name": "b", "repo_count": 2, "activity_score": 1.5, "total_usage": 10},
        {"name": "c", "repo_count": 5, "activity_score": 0.2, "total_usage": 20},
    ]
    result = analyzer.filter_and_sort_libraries(
        fields=["name", "repo_count", "activity_score"],
        sort_field="repo_count",
        sort_order="DESC",
        condition_field="repo_count",
        condition_value=0,
        condition_signal=1,
        limit=1,
    )
    assert len(result) == 1
    assert result[0]["name"] == "c"


def test_get_repository_count_by_year_handles_empty_or_missing_values():
    analyzer = _make_analyzer()
    analyzer.repo_info = [
        {"created_at": "2020-01-02T00:00:00", "affect_from_boost": True},
        {"created_at": "2020-05-02", "affect_from_boost": True},
        {"created_at": ""},
        {},
    ]
    out = analyzer._get_repository_count_by_year("created_at")
    assert out == {"2020": 2}


def test_collect_top_repositories_handles_mixed_value_types():
    analyzer = _make_analyzer()
    analyzer.repo_info = [
        {
            "repo_name": "a/b",
            "stars": 10,
            "usage_count": 3,
            "created_at": "2024-01-01T00:00:00",
        },
        {"repo_name": "c/d", "stars": 5, "usage_count": "", "created_at": ""},
        {
            "repo_name": "e/f",
            "stars": 20,
            "usage_count": 11,
            "created_at": "2025-01-01T00:00:00",
        },
        {"repo_name": "g/h", "stars": None, "usage_count": None, "created_at": None},
    ]
    out = analyzer._collect_top_repositories_for_dashboard()
    assert out["top20_by_stars"][0]["repo_name"] == "e/f"
    assert out["top20_by_usage"][0]["repo_name"] == "e/f"
    assert out["top20_by_created"][0]["repo_name"] == "e/f"


def test_load_repository_count_from_db_missing_model_returns_empty():
    analyzer = _make_analyzer()
    with patch(
        "boost_library_usage_dashboard.analyzer.apps.get_model",
        side_effect=LookupError("missing"),
    ):
        out = analyzer._load_repository_count_from_db({"2020": 3})
    assert out["repos_by_year_boost_rate"] == []
    assert out["language_comparison_data"] == {}
