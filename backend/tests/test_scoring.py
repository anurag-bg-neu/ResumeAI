"""Scoring paths that don't need the embedding model."""

from scoring.gap_analysis import analyze_skill_gaps
from scoring.semantic_scorer import compute_overall_semantic_score
from scoring.tfidf_scorer import score_with_tfidf


def _resume(skills, bullets=()):
    return {
        "sections": {"experience": [{"bullets": list(bullets)}], "projects": []},
        "all_skills_detected": skills,
    }


def _jd(required, preferred=(), sentences=()):
    return {
        "requirements": {
            "required_skills": list(required),
            "preferred_skills": list(preferred),
            "requirement_sentences": [{"text": s, "type": "required"} for s in sentences],
        }
    }


def test_gap_analysis_matches_canonical_names():
    resume = _resume(["React.js", "k8s", "Linux/Unix Terminal", "Express.js"])
    result = analyze_skill_gaps(resume, _jd(["React", "Kubernetes", "Unix"], ["Express"]))
    assert result == {
        "covered": ["React", "Kubernetes", "Unix", "Express"],
        "missing": [],
        "partial_match": [],
    }


def test_gap_analysis_no_loose_token_matches():
    # "Apache Airflow" must not cover "Apache Flink"; "C" must not cover "CSS".
    resume = _resume(["Apache Airflow", "C"])
    result = analyze_skill_gaps(resume, _jd(["Flink", "CSS"]))
    assert result["missing"] == ["Flink", "CSS"]


def test_gap_analysis_without_bullets_keeps_preferred_skills():
    result = analyze_skill_gaps(_resume([]), _jd(["Go"], ["Rust"]))
    assert result["missing"] == ["Go", "Rust"]


def test_tfidf_handles_jd_without_requirement_sentences():
    scored = score_with_tfidf(_resume([], ["Built REST APIs in Python"]), _jd(["Python"]))
    assert scored == [{
        "text": "Built REST APIs in Python",
        "section": "experience",
        "keyword_score": 0.0,
        "best_match_requirement": None,
    }]


def test_overall_semantic_score_is_a_weighted_mean():
    sections = {
        "experience": [{"section_weight": 1.5, "bullets": [{"semantic_score": 1.0}]}],
        "projects": [{"section_weight": 1.0, "bullets": [{"semantic_score": 1.0}]}],
    }
    # All bullets score 1.0, so the weighted mean is 1.0 — never above it.
    assert compute_overall_semantic_score(sections) == 1.0
