"""
baseline_tfidf.py
-----------------
This is the "dumb" baseline model. It treats every bullet and every JD requirement
as a bag of words, then measures how much they overlap using TF-IDF + cosine similarity.

It doesn't understand meaning — if the JD says "CI/CD pipelines" and the resume says
"automated deployment workflows", this will score it low even though they mean the same thing.
That's exactly the point. We use this as a comparison against the semantic model.
"""

import json
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def get_all_bullets(resume):
    """Pull every bullet point out of the resume into a flat list with section labels."""
    bullets = []

    for exp in resume["sections"].get("experience", []):
        for b in exp.get("bullets", []):
            bullets.append({"text": b, "section": "experience"})

    for proj in resume["sections"].get("projects", []):
        for b in proj.get("bullets", []):
            bullets.append({"text": b, "section": "projects"})

    # education usually doesn't have bullets, but handle it just in case
    for edu in resume["sections"].get("education", []):
        for detail in edu.get("details", []):
            bullets.append({"text": detail, "section": "education"})

    return bullets


def score_with_tfidf(resume, jd):
    """
    Score every resume bullet against every JD requirement using TF-IDF cosine similarity.

    Steps:
    1. Collect all the texts (bullets + requirements) into one list
    2. Fit a TF-IDF vectorizer on all of them so the word weights are shared
    3. For each bullet, compute cosine similarity against each requirement
    4. Each bullet's score = its best-matching requirement score (max across all requirements)
    """

    bullets = get_all_bullets(resume)
    requirements = jd["requirements"]["requirement_sentences"]

    # just the raw text strings
    bullet_texts = [b["text"] for b in bullets]
    req_texts = [r["text"] for r in requirements]

    # fit TF-IDF on everything together so word frequencies are calibrated across the full corpus
    all_texts = bullet_texts + req_texts
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(all_texts)

    # split back out: first N rows are bullets, rest are requirements
    bullet_vectors = tfidf_matrix[:len(bullet_texts)]
    req_vectors = tfidf_matrix[len(bullet_texts):]

    # cosine_similarity returns a matrix: rows = bullets, cols = requirements
    sim_matrix = cosine_similarity(bullet_vectors, req_vectors)

    # attach a keyword score to each bullet
    scored_bullets = []
    for i, bullet in enumerate(bullets):
        scores_against_all_reqs = sim_matrix[i]  # one score per requirement
        best_score = float(max(scores_against_all_reqs))
        best_req_idx = int(scores_against_all_reqs.argmax())
        best_req_text = req_texts[best_req_idx] if best_score > 0.01 else None

        scored_bullets.append({
            "text": bullet["text"],
            "section": bullet["section"],
            "keyword_score": round(best_score, 4),
            "best_match_requirement": best_req_text
        })

    return scored_bullets


def compute_overall_keyword_score(scored_bullets):
    """
    Overall keyword match score for the whole resume vs this JD.
    Just the average of all bullet keyword scores.
    """
    if not scored_bullets:
        return 0.0
    total = sum(b["keyword_score"] for b in scored_bullets)
    return round(total / len(scored_bullets), 4)


if __name__ == "__main__":
    # quick test — run this directly to see what scores come out
    with open("../data/mock_data/sample_resume.json") as f:
        resume = json.load(f)
    with open("../data/mock_data/sample_jd.json") as f:
        jd = json.load(f)

    scored = score_with_tfidf(resume, jd)
    overall = compute_overall_keyword_score(scored)

    print(f"Overall keyword score: {overall}")
    print("\nTop 5 bullets by keyword score:")
    top5 = sorted(scored, key=lambda x: x["keyword_score"], reverse=True)[:5]
    for b in top5:
        print(f"  [{b['keyword_score']:.2f}] {b['text'][:70]}")
