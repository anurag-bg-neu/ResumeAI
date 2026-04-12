"""
generate_resume.py
------------------
Modular CLI helper for the full ResumeAI pipeline (Stage 1 → 2 → 3).

Selects which resume PDF and which JD to use via command-line arguments,
runs the complete pipeline, identifies missing/partial skills, adds them
to the skills section if requested, and generates a tailored PDF resume.

Usage examples
--------------
# Basic: parse resume + score against a JD + generate PDF
python generate_resume.py \\
    --resume data/sample_resumes/milan.pdf \\
    --jd data/sample_jds/jd1.txt

# Add missing JD skills to the skills section before PDF generation
python generate_resume.py \\
    --resume data/sample_resumes/milan.pdf \\
    --jd data/sample_jds/jd2.txt \\
    --add-missing-skills \\
    --output results/

# Use pre-scored JSON (skip Stage 1 + 2 if already computed)
python generate_resume.py \\
    --scored data/mock_data/sample_scored.json \\
    --jd-json data/mock_data/sample_jd.json \\
    --add-missing-skills \\
    --output results/

# Multi-JD comparison (score one resume against all JDs in a folder)
python generate_resume.py \\
    --resume data/sample_resumes/milan.pdf \\
    --jd-dir data/sample_jds/ \\
    --multi-jd \\
    --output results/

Arguments
---------
--resume            Path to master resume PDF (Stage 1 input)
--jd                Path to a single JD .txt file (Stage 1 input)
--jd-json           Path to a pre-parsed JD JSON file (skip Stage 1 JD parsing)
--scored            Path to a pre-scored resume JSON (skip Stage 1 + 2 entirely)
--add-missing-skills  Flag: inject missing JD skills into the skills section
--multi-jd          Flag: run comparison across all JDs in --jd-dir
--jd-dir            Directory with JD .txt files (default: data/sample_jds/)
--output            Output directory for PDF and reports (default: results/)
--verbose           Enable DEBUG logging

Sample command to run this file to generate a fully updated resume:
python generate_resume.py --resume data/sample_resumes/milan.pdf --jd data/sample_jds/jd4.txt --add-missing-skills
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Force stdout to flush immediately — prevents interleaved print/logging on Windows
reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(reconfigure):
    reconfigure(line_buffering=True)

# ── ensure repo root is on sys.path regardless of invocation directory ────────
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from person1_parsing.resume_parser import parse_resume
from person1_parsing.jd_parser import parse_jd
from person2_scoring.scorer import score_resume
from person3_generation.assembler import assemble_resume
from person3_generation.latex_generator import generate_resume_pdf
from person3_generation.multi_jd_compare import (
    run_multi_jd_comparison,
    print_multi_jd_summary,
)

# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

SEP = "=" * 72
THIN = "-" * 72


def _header(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def _print_gap_report(gap_report: dict) -> None:
    _header("SKILL GAP REPORT")
    missing = gap_report.get("missing_skills", [])
    partial = gap_report.get("partial_matches", [])

    jd_label = gap_report.get("jd_title", "")
    if gap_report.get("jd_company"):
        jd_label += f" @ {gap_report['jd_company']}"
    print(f"\n  Role: {jd_label or '(unknown)'}")

    if missing:
        print(f"\n  Missing skills ({len(missing)}) — add to resume if you have them:")
        for s in missing:
            print(f"    ✗  {s}")
    else:
        print("\n  No missing required/preferred skills detected.")

    if partial:
        print(f"\n  Partial matches ({len(partial)}) — consider rewording:")
        for p in partial:
            sim = p.get("similarity", 0.0)
            print(f"    ~  JD wants: \"{p['jd_skill']}\"  (similarity: {sim:.3f})")
            print(f"       Closest bullet: \"{p['closest_bullet'][:75]}\"")

    print(f"\n  Recommendation: {gap_report.get('recommendation', '')}\n")


def _print_assembly_summary(assembled: dict) -> None:
    _header("ASSEMBLY SUMMARY")
    exp = assembled.get("experience", [])
    proj = assembled.get("projects", [])
    # skills is now {"flat": [...], "categorized": [...]} — extract flat list
    skills_raw = assembled.get("skills", [])
    skills = skills_raw.get("flat", []) if isinstance(skills_raw, dict) else skills_raw
    scores = assembled.get("overall_scores", {})

    print(f"\n  Semantic score : {scores.get('semantic', 0.0):.4f}")
    print(f"  Keyword score  : {scores.get('keyword', 0.0):.4f}")
    print(f"\n  Experiences included : {len(exp)}")
    for e in exp:
        print(
            f"    • {e.get('company', '?')} — {e.get('title', '?')}"
            f"  (avg relevance: {e.get('avg_relevance', 0.0):.3f},"
            f" {len(e.get('bullets', []))} bullets)"
        )
    print(f"\n  Projects included    : {len(proj)}")
    for p in proj:
        print(
            f"    • {p.get('name', '?')}  (avg relevance: {p.get('avg_relevance', 0.0):.3f})"
        )
    print(
        f"\n  Skills in output ({len(skills)}): {', '.join(skills[:12])}"
        + (" …" if len(skills) > 12 else "")
    )


# ─────────────────────────────────────────────────────────────────────────────
# CORE PIPELINE STEPS
# ─────────────────────────────────────────────────────────────────────────────


def _stage1_parse(resume_path: str, jd_source: str) -> tuple[dict, dict]:
    """Run Stage 1: parse PDF resume and JD text into dicts."""
    print(f"\n[Stage 1] Parsing resume: {resume_path}")
    resume = parse_resume(resume_path)
    print(
        f"  → {len(resume['sections']['experience'])} experiences, "
        f"{len(resume['sections']['projects'])} projects, "
        f"{len(resume['all_skills_detected'])} skills"
    )

    if Path(jd_source).is_file():
        with open(jd_source, encoding="utf-8", errors="ignore") as fh:
            jd_text = fh.read()
        print(f"\n[Stage 1] Parsing JD: {jd_source}")
    else:
        jd_text = jd_source
        print(f"\n[Stage 1] Parsing JD from raw text ({len(jd_text)} chars)")

    jd = parse_jd(jd_text)
    print(
        f"  → Role: {jd.get('title', '(unknown)')} @ {jd.get('company', '(unknown)')}"
    )
    print(
        f"  → {len(jd['requirements']['required_skills'])} required skills, "
        f"{len(jd['requirements']['preferred_skills'])} preferred skills"
    )
    return resume, jd


def _stage2_score(resume: dict, jd: dict) -> dict:
    """Run Stage 2: score the resume against the JD."""
    print("\n[Stage 2] Scoring resume against JD...")
    scored = score_resume(resume, jd)
    print(f"  → Semantic score: {scored['overall_semantic_score']:.4f}")
    print(f"  → Keyword score : {scored['overall_keyword_score']:.4f}")
    print(f"  → Covered skills: {scored['skills_analysis']['covered']}")
    print(f"  → Missing skills: {scored['skills_analysis']['missing']}")
    return scored


def _inject_missing_skills(assembled: dict, gap_report: dict) -> dict:
    """
    Inject missing JD skills into the assembled resume's skills list
    (appended after existing skills so they appear on the PDF).

    This directly improves ATS keyword coverage for the targeted JD.
    Only adds skills that aren't already present (case-insensitive check).
    """
    missing = gap_report.get("missing_skills", [])
    if not missing:
        return assembled

    # skills is a dict {"flat": [...], "categorized": [...]}
    skills_data = assembled.get("skills", {})
    if isinstance(skills_data, dict):
        flat = skills_data.get("flat", [])
        cats = skills_data.get("categorized", [])
    else:
        flat = skills_data
        cats = [{"category": "Skills", "skills": skills_data}]

    existing_lower = {s.lower() for s in flat}
    newly_added = [s for s in missing if s.lower() not in existing_lower]

    if newly_added:
        flat = flat + newly_added
        # Also append to last category so they appear in categorized skills
        if cats:
            cats[-1]["skills"] = cats[-1]["skills"] + newly_added
        assembled["skills"] = {"flat": flat, "categorized": cats}
        print(
            f"\n  [+] Injected {len(newly_added)} missing skill(s) into skills section: "
            f"{', '.join(newly_added)}"
        )
    else:
        print("\n  [i] No new skills to inject (all missing skills already present).")

    return assembled


def _stage3_generate(assembled: dict, output_dir: str, stem: str) -> str:
    """Run Stage 3: generate PDF from assembled resume data."""
    print(f"\n[Stage 3] Generating tailored resume PDF → {output_dir}/{stem}.pdf")
    pdf_path = generate_resume_pdf(assembled, output_dir=output_dir, filename_stem=stem)
    print(f"  → PDF saved: {pdf_path}")
    return pdf_path


def _save_gap_report_json(gap_report: dict, output_dir: str, stem: str) -> str:
    """Save the gap report as a JSON file alongside the PDF."""
    out_path = Path(output_dir) / f"{stem}_gap_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(gap_report, fh, indent=2)
    print(f"  → Gap report saved: {out_path}")
    return str(out_path)


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE-JD PIPELINE
# ─────────────────────────────────────────────────────────────────────────────


def run_single_jd_pipeline(args: argparse.Namespace) -> None:
    """
    Full single-JD pipeline:
    Stage 1 → Stage 2 → Stage 3 assembly → (optionally inject missing skills) → PDF
    """
    output_dir = str(
        Path(args.output)
    )  # normalize: removes trailing slash / double slash

    # ── Load or compute scored output ────────────────────────────────────────
    if args.scored:
        # Pre-scored JSON provided — skip Stages 1 & 2
        print(f"\n[Stage 1+2] Loading pre-scored JSON: {args.scored}")
        with open(args.scored, encoding="utf-8") as fh:
            scored = json.load(fh)

        if args.jd_json:
            print(f"[Stage 1] Loading pre-parsed JD JSON: {args.jd_json}")
            with open(args.jd_json, encoding="utf-8") as fh:
                jd = json.load(fh)
        else:
            # Build a minimal jd dict so assembly works without a JD file
            jd = {
                "title": "",
                "company": "",
                "requirements": {
                    "required_skills": [],
                    "preferred_skills": [],
                    "experience_years": None,
                    "requirement_sentences": [],
                },
                "raw_text": "",
            }

    else:
        # Full pipeline from scratch
        if not args.resume:
            print("[ERROR] --resume is required when --scored is not provided.")
            sys.exit(1)
        if not args.jd and not args.jd_json:
            print("[ERROR] Either --jd or --jd-json is required.")
            sys.exit(1)

        jd_source = args.jd if args.jd else args.jd_json
        resume, jd = _stage1_parse(args.resume, jd_source)
        scored = _stage2_score(resume, jd)

        # Stash contact info into scored so assembler can pass it through
        scored["contact"] = resume.get("contact", {})

    # ── Stage 3: Assemble ────────────────────────────────────────────────────
    print("\n[Stage 3] Assembling tailored resume...")
    # Pass full resume dict so assembler can restore all original bullets and extra sections
    full_resume = locals().get("resume", None)  # available when full pipeline ran
    assembled = assemble_resume(scored, jd, resume=full_resume)
    _print_assembly_summary(assembled)
    _print_gap_report(assembled["gap_report"])

    # ── Optionally inject missing skills ─────────────────────────────────────
    if args.add_missing_skills:
        assembled = _inject_missing_skills(assembled, assembled["gap_report"])

    # ── Generate PDF ─────────────────────────────────────────────────────────
    # Use JD company name if available, otherwise fall back to JD filename stem
    jd_company = jd.get("company", "").strip()
    if jd_company:
        jd_slug = jd_company.lower().replace(" ", "_")[:20]
    elif args.jd and Path(args.jd).stem:
        jd_slug = Path(args.jd).stem.lower()[:20]  # e.g. "jd1"
    elif args.jd_json and Path(args.jd_json).stem:
        jd_slug = Path(args.jd_json).stem.lower()[:20]
    else:
        jd_slug = "resume"
    stem = f"tailored_resume_{jd_slug}"
    pdf_path = _stage3_generate(assembled, output_dir, stem)
    _save_gap_report_json(assembled["gap_report"], output_dir, stem)

    _header("DONE")
    print(f"\n  PDF resume  : {pdf_path}")
    print(f"  Output dir  : {Path(output_dir).resolve()}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-JD PIPELINE
# ─────────────────────────────────────────────────────────────────────────────


def run_multi_jd_pipeline(args: argparse.Namespace) -> None:
    """
    Multi-JD comparison pipeline:
    Parse one resume → score against each JD in --jd-dir → heatmap + summary.
    """
    output_dir = str(Path(args.output))  # normalize path
    jd_dir = Path(args.jd_dir)

    if not jd_dir.is_dir():
        print(f"[ERROR] --jd-dir does not exist: {jd_dir}")
        sys.exit(1)

    jd_files = sorted(jd_dir.glob("*.txt"))
    if not jd_files:
        print(f"[ERROR] No .txt JD files found in: {jd_dir}")
        sys.exit(1)

    if not args.resume:
        print("[ERROR] --resume is required for multi-JD comparison.")
        sys.exit(1)

    _header(f"MULTI-JD COMPARISON ({len(jd_files)} JDs)")
    print(f"\n  Resume : {args.resume}")
    print(f"  JD dir : {jd_dir}")
    print(f"  JDs    : {', '.join(f.name for f in jd_files)}\n")

    # Parse resume once
    print("[Stage 1] Parsing resume PDF...")
    resume = parse_resume(args.resume)
    print(
        f"  → {len(resume['sections']['experience'])} experiences, "
        f"{len(resume['sections']['projects'])} projects"
    )

    scored_outputs: dict[str, dict] = {}

    for jd_file in jd_files:
        print(f"\n[Stage 1+2] Processing JD: {jd_file.name}")
        with open(jd_file, encoding="utf-8", errors="ignore") as fh:
            jd_text = fh.read()
        jd = parse_jd(jd_text)
        print(f"  → {jd.get('title', '?')} @ {jd.get('company', '?')}")
        scored = score_resume(resume, jd)
        scored["contact"] = resume.get("contact", {})
        label = jd_file.stem
        scored_outputs[label] = scored
        print(
            f"  → Semantic: {scored['overall_semantic_score']:.4f}  "
            f"Keyword: {scored['overall_keyword_score']:.4f}"
        )

    # Run comparison
    print("\n[Stage 3] Running multi-JD comparison analysis...")
    results = run_multi_jd_comparison(
        scored_outputs,
        output_dir=output_dir,
        heatmap_filename="multi_jd_heatmap.png",
    )
    print_multi_jd_summary(results)

    # Save bullet analysis CSV
    csv_path = Path(output_dir) / "bullet_analysis.csv"
    results["bullet_analysis"].to_csv(str(csv_path), index=False)
    print(f"  Bullet analysis CSV: {csv_path.resolve()}")

    # Optionally generate a PDF for the best-scoring JD
    best_jd_label = max(
        scored_outputs,
        key=lambda k: scored_outputs[k]["overall_semantic_score"],
    )
    print(
        f"\n  Best-matching JD: {best_jd_label} "
        f"(semantic={scored_outputs[best_jd_label]['overall_semantic_score']:.4f})"
    )

    if args.add_missing_skills or True:  # always generate for best JD in multi mode
        best_scored = scored_outputs[best_jd_label]
        # Re-parse the best JD to get full jd dict for assembler
        best_jd_path = jd_dir / f"{best_jd_label}.txt"
        with open(best_jd_path, encoding="utf-8", errors="ignore") as fh:
            best_jd = parse_jd(fh.read())
        assembled = assemble_resume(best_scored, best_jd, resume=resume)
        if args.add_missing_skills:
            assembled = _inject_missing_skills(assembled, assembled["gap_report"])
        pdf_path = _stage3_generate(
            assembled, output_dir, f"best_match_{best_jd_label}"
        )
        print(f"  Best-match PDF  : {pdf_path}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="generate_resume",
        description="ResumeAI — full pipeline helper (Stage 1 → 2 → 3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Input sources
    ap.add_argument(
        "--resume", default=None, help="Path to master resume PDF (Stage 1 input)"
    )
    ap.add_argument("--jd", default=None, help="Path to a single JD .txt file")
    ap.add_argument(
        "--jd-json",
        default=None,
        help="Path to a pre-parsed JD JSON (skip Stage 1 JD parsing)",
    )
    ap.add_argument(
        "--scored",
        default=None,
        help="Path to a pre-scored resume JSON (skip Stage 1 + 2)",
    )

    # Behavior flags
    ap.add_argument(
        "--add-missing-skills",
        action="store_true",
        default=False,
        help="Inject missing JD skills into the skills section before generating PDF",
    )
    ap.add_argument(
        "--multi-jd",
        action="store_true",
        default=False,
        help="Run multi-JD comparison across all JDs in --jd-dir",
    )
    ap.add_argument(
        "--jd-dir",
        default="data/sample_jds/",
        help="Directory of JD .txt files for multi-JD mode (default: data/sample_jds/)",
    )

    # Output
    ap.add_argument(
        "--output",
        default="results/",
        help="Output directory for PDF + reports (default: results/)",
    )
    ap.add_argument(
        "--verbose", action="store_true", default=False, help="Enable DEBUG logging"
    )

    return ap


def main() -> None:
    ap = _build_parser()
    args = ap.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(levelname)s | %(name)s | %(message)s",
        level=log_level,
    )

    # Suppress sentence_transformers INFO noise unless verbose
    if not args.verbose:
        logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
        logging.getLogger("transformers").setLevel(logging.WARNING)

    if args.multi_jd:
        run_multi_jd_pipeline(args)
    else:
        run_single_jd_pipeline(args)


if __name__ == "__main__":
    main()
