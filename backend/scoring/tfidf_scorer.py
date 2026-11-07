"""
tfidf_scorer.py
---------------
This is the "dumb" baseline model. It treats every bullet and every JD requirement
as a bag of words, then measures how much they overlap using TF-IDF + cosine similarity.

It doesn't understand meaning — if the JD says "CI/CD pipelines" and the resume says
"automated deployment workflows", this will score it low even though they mean the same thing.
That's exactly the point. We use this as a comparison against the semantic model.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .bullets import iter_bullets

# Below this cosine similarity a bullet shares no meaningful vocabulary with
# any requirement, so no "best match" is reported.
MATCH_FLOOR: float = 0.01


def score_with_tfidf(resume, jd):
    """
    Score every resume bullet against every JD requirement using TF-IDF cosine similarity.

    Steps:
    1. Collect all the texts (bullets + requirements) into one list
    2. Fit a TF-IDF vectorizer on all of them so the word weights are shared
    3. For each bullet, compute cosine similarity against each requirement
    4. Each bullet's score = its best-matching requirement score (max across all requirements)
    """
    bullets = [(section, text) for section, _, _, text in iter_bullets(resume)]
    req_texts = [r["text"] for r in jd["requirements"]["requirement_sentences"]]

    # A JD with no parseable requirement sentences (e.g. "Python, Go") leaves
    # nothing to compare against: every bullet scores 0 instead of crashing.
    if not bullets or not req_texts:
        return [
            {"text": text, "section": section, "keyword_score": 0.0, "best_match_requirement": None}
            for section, text in bullets
        ]

    # fit TF-IDF on everything together so word frequencies are calibrated across the full corpus
    bullet_texts = [text for _, text in bullets]
    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        tfidf_matrix = vectorizer.fit_transform(bullet_texts + req_texts)
    except ValueError:  # every token was a stop word: empty vocabulary
        return [
            {"text": text, "section": section, "keyword_score": 0.0, "best_match_requirement": None}
            for section, text in bullets
        ]

    # split back out: first N rows are bullets, rest are requirements
    # cosine_similarity returns a matrix: rows = bullets, cols = requirements
    sim_matrix = cosine_similarity(tfidf_matrix[: len(bullets)], tfidf_matrix[len(bullets) :])

    scored_bullets = []
    for i, (section, text) in enumerate(bullets):
        best_req_idx = int(sim_matrix[i].argmax())
        best_score = float(sim_matrix[i][best_req_idx])
        scored_bullets.append({
            "text": text,
            "section": section,
            "keyword_score": round(best_score, 4),
            "best_match_requirement": req_texts[best_req_idx] if best_score > MATCH_FLOOR else None,
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
