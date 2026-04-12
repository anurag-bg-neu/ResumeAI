"""
test_scoring.py
---------------
Quick helper to validate Person 2's scoring pipeline.

Runs two modes:
  1. Mock data   — uses data/mock_data/ JSON files (no PDF parsing needed)
  2. Full pipeline — parses real PDF + JD text through Person 1 → Person 2

Usage (from repo root):
    python test_scoring.py
"""

import json
import os
import sys

# ensure repo root is on sys.path so subpackage imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from person2_scoring.scorer import score_resume


# ── display helpers ──────────────────────────────────────────────────────────

SEPARATOR = "=" * 72
THIN_SEP = "-" * 72


def print_header(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def print_bullet_table(bullets: list[dict], top_n: int = 5) -> None:
    """Print a ranked table of bullets with both scores."""
    sorted_bullets = sorted(
        bullets,
        key=lambda b: b.get("semantic_score", 0.0),
        reverse=True,
    )
    print(f"\n  {'Rank':<5} {'Semantic':>9} {'Keyword':>9}  {'Bullet (truncated)'}")
    print(f"  {'----':<5} {'--------':>9} {'-------':>9}  {'------------------'}")
    for i, b in enumerate(sorted_bullets[:top_n], 1):
        sem = b.get("semantic_score", 0.0)
        kw = b.get("keyword_score", 0.0)
        text = b["text"][:65]
        print(f"  {i:<5} {sem:>9.4f} {kw:>9.4f}  {text}")


def display_results(result: dict, label: str) -> None:
    """Pretty-print the full scored output to the terminal."""
    print_header(f"RESULTS — {label}")

    # overall scores
    print(f"\n  Overall Semantic Score : {result['overall_semantic_score']:.4f}")
    print(f"  Overall Keyword Score  : {result['overall_keyword_score']:.4f}")

    # skills analysis
    sa = result["skills_analysis"]
    print(f"\n  Covered skills  ({len(sa['covered'])}): {', '.join(sa['covered']) or '(none)'}")
    print(f"  Missing skills  ({len(sa['missing'])}): {', '.join(sa['missing']) or '(none)'}")
    if sa["partial_match"]:
        print(f"  Partial matches ({len(sa['partial_match'])}):")
        for p in sa["partial_match"]:
            print(f"    • JD wants: \"{p['jd_skill']}\"  (similarity: {p['similarity']:.4f})")
            print(f"      Closest bullet: \"{p['closest_bullet'][:70]}\"")

    # per-section breakdown
    scored = result["scored_sections"]

    for section_name in ["experience", "projects"]:
        entries = scored.get(section_name, [])
        if not entries:
            continue
        print(f"\n{THIN_SEP}")
        print(f"  Section: {section_name.upper()}")
        print(THIN_SEP)

        for entry in entries:
            # experience entries have company/title; projects have name
            if section_name == "experience":
                heading = f"{entry.get('company', '?')} — {entry.get('title', '?')}"
            else:
                heading = entry.get("name", "Unnamed Project")

            weight = entry.get("section_weight", 1.0)
            avg = entry.get("avg_relevance", 0.0)
            n_bullets = len(entry.get("bullets", []))

            print(f"\n  {heading}")
            print(f"    Section weight : {weight}")
            print(f"    Avg relevance  : {avg:.4f}")
            print(f"    Total bullets  : {n_bullets}")

            if entry.get("bullets"):
                print_bullet_table(entry["bullets"], top_n=5)


# ── Mode 1: mock data ───────────────────────────────────────────────────────

def run_mock_test() -> None:
    print_header("MODE 1 — MOCK DATA TEST")
    print("  Loading data/mock_data/sample_resume.json + sample_jd.json\n")

    mock_dir = os.path.join(os.path.dirname(__file__), "data", "mock_data")
    resume_path = os.path.join(mock_dir, "sample_resume.json")
    jd_path = os.path.join(mock_dir, "sample_jd.json")

    with open(resume_path) as f:
        resume = json.load(f)
    with open(jd_path) as f:
        jd = json.load(f)

    result = score_resume(resume, jd)
    display_results(result, "Mock Data (sample_resume vs sample_jd)")


# ── Mode 2: full pipeline (PDF + JD .txt) ───────────────────────────────────

def run_full_pipeline_test() -> None:
    from person1_parsing.resume_parser import parse_resume as parse_resume_pdf
    from person1_parsing.jd_parser import parse_jd

    resume_pdf = os.path.join(os.path.dirname(__file__), "data", "sample_resumes", "milan.pdf")
    jd_dir = os.path.join(os.path.dirname(__file__), "data", "sample_jds")

    if not os.path.isfile(resume_pdf):
        print(f"\n  [SKIP] Resume PDF not found: {resume_pdf}")
        return

    jd_files = sorted(f for f in os.listdir(jd_dir) if f.endswith(".txt"))
    if not jd_files:
        print(f"\n  [SKIP] No JD .txt files found in {jd_dir}")
        return

    print_header("MODE 2 — FULL PIPELINE (PDF + JD TEXT FILES)")
    print(f"  Resume : {resume_pdf}")
    print(f"  JDs    : {', '.join(jd_files)}\n")

    # parse the resume once
    print("  Parsing resume PDF...")
    resume = parse_resume_pdf(resume_pdf)
    print(f"  → {len(resume['sections']['experience'])} experience entries, "
          f"{len(resume['sections']['projects'])} projects, "
          f"{len(resume['all_skills_detected'])} skills detected\n")

    # score against each JD
    for jd_file in jd_files:
        jd_path = os.path.join(jd_dir, jd_file)
        with open(jd_path, encoding='utf-8', errors='ignore') as f:  # ← using full path
            jd_text = f.read()

        print(f"\n  Parsing JD: {jd_file} ...")
        jd = parse_jd(jd_text)
        print(f"  → Role: {jd['title'] or '(not detected)'} @ {jd['company'] or '(not detected)'}")
        print(f"  → {len(jd['requirements']['required_skills'])} required, "
              f"{len(jd['requirements']['preferred_skills'])} preferred skills")

        result = score_resume(resume, jd)
        display_results(result, f"milan.pdf vs {jd_file}")


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  ResumeAI — Person 2 Scoring Test Harness")
    print("  ----------------------------------------\n")

    run_mock_test()
    run_full_pipeline_test()

    print(f"\n{SEPARATOR}")
    print("  ALL TESTS COMPLETE")
    print(SEPARATOR)
