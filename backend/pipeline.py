"""
pipeline.py
-----------
Wires all 3 stages together into one end-to-end run.

Usage:
    python pipeline.py --resume data/sample_resumes/milan.pdf --jd data/sample_jds/jd1.txt
    python pipeline.py --resume data/sample_resumes/milan.pdf --jd data/sample_jds/jd1.txt --output results/scored.json

What it does:
    Stage 1 (Person 1): parse the PDF resume + JD text into clean JSON
    Stage 2 (Person 2): score every bullet semantically and with TF-IDF, run gap analysis
    Stage 3 output:     save the scored JSON so Person 3 can pick it up for resume assembly
"""

import argparse
import json
import os
import sys

# make sure the sub-packages are importable when running from the repo root
sys.path.insert(0, os.path.dirname(__file__))

from person1_parsing.resume_parser import parse_resume
from person1_parsing.jd_parser import parse_jd
from person2_scoring.scorer import score_resume


def run_pipeline(resume_pdf_path, jd_source, output_path=None):
    """
    Full pipeline: PDF + JD text -> scored JSON ready for Person 3.

    resume_pdf_path: path to the master resume PDF
    jd_source:       either a path to a .txt file or raw JD text as a string
    output_path:     where to save the scored JSON (optional)
    """

    # ── Stage 1: parse ──────────────────────────────────────────────────────
    print(f"\n[Stage 1] Parsing resume: {resume_pdf_path}")
    resume = parse_resume(resume_pdf_path)
    print(f"  Parsed {len(resume['sections']['experience'])} experience entries, "
          f"{len(resume['sections']['projects'])} projects, "
          f"{len(resume['all_skills_detected'])} skills detected")

    # figure out if jd_source is a file path or raw text
    if os.path.isfile(jd_source):
        with open(jd_source) as f:
            jd_text = f.read()
        print(f"\n[Stage 1] Parsing JD from file: {jd_source}")
    else:
        jd_text = jd_source
        print(f"\n[Stage 1] Parsing JD from raw text ({len(jd_text)} chars)")

    jd = parse_jd(jd_text)
    print(f"  Role: {jd['title']} @ {jd['company']}")
    print(f"  {len(jd['requirements']['required_skills'])} required skills, "
          f"{len(jd['requirements']['preferred_skills'])} preferred skills")

    # ── Stage 2: score ──────────────────────────────────────────────────────
    print(f"\n[Stage 2] Scoring resume against JD...")
    scored = score_resume(resume, jd)

    print(f"\n  Overall semantic score: {scored['overall_semantic_score']}")
    print(f"  Overall keyword score:  {scored['overall_keyword_score']}")
    print(f"  Covered skills:  {scored['skills_analysis']['covered']}")
    print(f"  Missing skills:  {scored['skills_analysis']['missing']}")
    if scored['skills_analysis']['partial_match']:
        print(f"  Partial matches: {[p['jd_skill'] for p in scored['skills_analysis']['partial_match']]}")

    # ── Save output ─────────────────────────────────────────────────────────
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
        with open(output_path, "w") as f:
            json.dump(scored, f, indent=2)
        print(f"\n[Done] Scored output saved to: {output_path}")
    else:
        print("\n[Done] (pass --output <path> to save the scored JSON)")

    return scored


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ResumeAI — end-to-end pipeline")
    ap.add_argument("--resume", required=True, help="Path to master resume PDF")
    ap.add_argument("--jd", required=True, help="Path to JD text file (or raw JD text)")
    ap.add_argument("--output", default=None, help="Where to save scored JSON output")
    args = ap.parse_args()

    run_pipeline(args.resume, args.jd, args.output)
