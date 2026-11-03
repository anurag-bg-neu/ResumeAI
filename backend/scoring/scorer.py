"""
scorer.py
---------
This is the main entry point for Stage 2. It takes the two JSON files from Person 1
and produces the scored JSON that Person 3 needs to assemble the final resume.

Run it like:
    python scorer.py resume.json jd.json scored_output.json

Or import score_resume() into pipeline.py to wire all 3 stages together.
"""

import json
import sys

# support both: running directly from person2_scoring/ OR importing from repo root via pipeline.py
try:
    from baseline_tfidf import score_with_tfidf, compute_overall_keyword_score
    from semantic_scorer import score_with_semantic, compute_overall_semantic_score
    from gap_analysis import analyze_skill_gaps
except ImportError:
    from person2_scoring.baseline_tfidf import score_with_tfidf, compute_overall_keyword_score
    from person2_scoring.semantic_scorer import score_with_semantic, compute_overall_semantic_score
    from person2_scoring.gap_analysis import analyze_skill_gaps


def score_resume(resume, jd):
    """
    Full scoring pipeline. Takes parsed resume + jd dicts, returns the scored JSON
    that matches the Person 2 -> Person 3 contract defined in our workflow doc.
    """

    print("Running TF-IDF baseline scoring...")
    tfidf_bullets = score_with_tfidf(resume, jd)
    overall_keyword = compute_overall_keyword_score(tfidf_bullets)

    # build a quick lookup from bullet text -> keyword score so we can attach it later
    keyword_lookup = {b["text"]: b["keyword_score"] for b in tfidf_bullets}

    print("Running semantic scoring (loading model, may take a moment first time)...")
    scored_sections = score_with_semantic(resume, jd)
    overall_semantic = compute_overall_semantic_score(scored_sections)

    # attach the keyword score to each bullet in the semantic output
    # (semantic_scorer only adds semantic_score, so we merge both here)
    for section_name in ["experience", "projects"]:
        for entry in scored_sections.get(section_name, []):
            for bullet in entry.get("bullets", []):
                bullet["keyword_score"] = keyword_lookup.get(bullet["text"], 0.0)

    print("Running skill gap analysis...")
    skills_analysis = analyze_skill_gaps(resume, jd)

    # assemble final output matching the JSON contract
    output = {
        "scored_sections": scored_sections,
        "skills_analysis": skills_analysis,
        "overall_semantic_score": overall_semantic,
        "overall_keyword_score": overall_keyword
    }

    return output


if __name__ == "__main__":
    # can run from command line: python scorer.py resume.json jd.json output.json
    if len(sys.argv) == 4:
        resume_path, jd_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
    else:
        # default to mock data for quick testing
        resume_path = "../data/mock_data/sample_resume.json"
        jd_path = "../data/mock_data/sample_jd.json"
        output_path = "../data/mock_data/sample_scored.json"

    with open(resume_path) as f:
        resume = json.load(f)
    with open(jd_path) as f:
        jd = json.load(f)

    result = score_resume(resume, jd)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nDone! Scored output saved to {output_path}")
    print(f"Overall semantic score: {result['overall_semantic_score']}")
    print(f"Overall keyword score:  {result['overall_keyword_score']}")
    print(f"Covered skills:  {result['skills_analysis']['covered']}")
    print(f"Missing skills:  {result['skills_analysis']['missing']}")
