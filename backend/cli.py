"""
cli.py
------
Command-line entry point for the full ResumeAI pipeline (Stage 1 → 2 → 3).

Selects which resume PDF and which JD to use via command-line arguments,
runs the complete pipeline, identifies missing/partial skills, adds them
to the skills section if requested, and generates a tailored PDF resume.

The stage wiring itself lives in pipeline.py — this module is presentation
and argument handling only.

Usage examples
--------------
# Basic: parse resume + score against a JD + generate PDF
python cli.py \\
    --resume data/sample_resumes/resume.pdf \\
    --jd data/sample_jds/jd1.txt

# Add missing JD skills to the skills section before PDF generation
python cli.py \\
    --resume data/sample_resumes/resume.pdf \\
    --jd data/sample_jds/jd2.txt \\
    --add-missing-skills \\
    --output results/

# Re-assemble from a previous run's scores (skip Stage 1 + 2). Every single-JD
# run writes <stem>_scored.json next to its PDF for exactly this.
python cli.py \\
    --scored results/tailored_resume_jd1_scored.json \\
    --jd-json data/mock_data/sample_jd.json \\
    --add-missing-skills \\
    --output results/

# Multi-JD comparison (score one resume against all JDs in a folder)
python cli.py \\
    --resume data/sample_resumes/resume.pdf \\
    --jd-dir data/sample_jds/ \\
    --multi-jd \\
    --output results/

Arguments
---------
--resume            Path to master resume PDF (Stage 1 input)
--jd                Path to a single JD .txt file (Stage 1 input)
--jd-json           Path to a pre-parsed JD JSON file (skip Stage 1 JD parsing)
--scored            Path to a <stem>_scored.json from an earlier run (skip Stage 1 + 2)
--add-missing-skills  Flag: inject missing JD skills into the skills section
--multi-jd          Flag: run comparison across all JDs in --jd-dir
--jd-dir            Directory with JD .txt files (default: data/sample_jds/)
--output            Output directory for PDF and reports (default: results/)
--verbose           Enable DEBUG logging

Sample command to run this file to generate a fully updated resume:
python cli.py --resume data/sample_resumes/resume.pdf --jd data/sample_jds/jd4.txt --add-missing-skills
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from generation.assembler import assemble_resume, inject_missing_skills
from generation.pdf_generator import generate_resume_pdf
from parsing.jd_parser import parse_jd
from parsing.resume_parser import parse_resume
from pipeline import run_pipeline
from scoring.scorer import score_resume

# generation.multi_jd_compare is imported lazily inside run_multi_jd_pipeline:
# it pulls pandas/matplotlib/seaborn, which --multi-jd runs should pay for and
# ordinary single-JD runs should not.

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


def _read_jd_text(jd_source: str) -> str:
    """Accept either a path to a .txt JD or the raw JD text itself."""
    if Path(jd_source).is_file():
        print(f"\n[Stage 1] Reading JD: {jd_source}")
        return Path(jd_source).read_text(encoding="utf-8", errors="ignore")
    print(f"\n[Stage 1] Using raw JD text ({len(jd_source)} chars)")
    return jd_source


def _print_injected(added: list[str]) -> None:
    if added:
        print(
            f"\n  [+] Injected {len(added)} missing skill(s) into skills section: "
            f"{', '.join(added)}"
        )
    else:
        print("\n  [i] No new skills to inject (all missing skills already present).")


def _stage3_generate(assembled: dict, output_dir: str, stem: str) -> str:
    """Run Stage 3: generate PDF from assembled resume data."""
    print(f"\n[Stage 3] Generating tailored resume PDF → {output_dir}/{stem}.pdf")
    pdf_path = generate_resume_pdf(assembled, output_dir=output_dir, filename_stem=stem)
    print(f"  → PDF saved: {pdf_path}")
    return pdf_path


def _save_json(data: dict, output_dir: str, filename: str, label: str) -> str:
    """Write one of the run's JSON artifacts alongside the PDF."""
    out_path = Path(output_dir) / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(f"  → {label} saved: {out_path}")
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

    if args.scored:
        # ── Pre-scored JSON provided — skip Stages 1 & 2 ─────────────────────
        print(f"\n[Stage 1+2] Loading pre-scored JSON: {args.scored}")
        with open(args.scored, encoding="utf-8") as fh:
            scored = json.load(fh)

        if args.jd_json:
            print(f"[Stage 1] Loading pre-parsed JD JSON: {args.jd_json}")
            with open(args.jd_json, encoding="utf-8") as fh:
                jd = json.load(fh)
        else:
            # Minimal jd dict so assembly works without a JD file
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

        # No parsed resume here: skill categories and extra sections are
        # unavailable, so the assembler falls back to the flat skill list.
        print("\n[Stage 3] Assembling tailored resume...")
        assembled = assemble_resume(scored, jd, resume=None)
        _print_assembly_summary(assembled)
        _print_gap_report(assembled["gap_report"])
        if args.add_missing_skills:
            _print_injected(inject_missing_skills(assembled, assembled["gap_report"]))

    else:
        # ── Full pipeline from scratch ───────────────────────────────────────
        if not args.resume:
            print("[ERROR] --resume is required when --scored is not provided.")
            sys.exit(1)
        if not args.jd and not args.jd_json:
            print("[ERROR] Either --jd or --jd-json is required.")
            sys.exit(1)

        if args.jd:
            jd_text, parsed_jd = _read_jd_text(args.jd), None
        else:
            print(f"\n[Stage 1] Loading pre-parsed JD JSON: {args.jd_json}")
            with open(args.jd_json, encoding="utf-8") as fh:
                jd_text, parsed_jd = "", json.load(fh)

        # output_dir=None: run stages 1-3 but defer PDF writing, because the
        # output filename depends on the JD company name we only learn here.
        result = run_pipeline(
            args.resume,
            jd_text,
            jd=parsed_jd,
            output_dir=None,
            add_missing_skills=args.add_missing_skills,
        )
        jd, assembled, scored = result.jd, result.assembled, result.scored

        _print_assembly_summary(assembled)
        _print_gap_report(assembled["gap_report"])
        if args.add_missing_skills:
            _print_injected(result.injected_skills)

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
    _save_json(assembled["gap_report"], output_dir, f"{stem}_gap_report.json", "Gap report")
    if not args.scored:
        _save_json(scored, output_dir, f"{stem}_scored.json", "Scores")

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
    # Deferred: drags in pandas/matplotlib/seaborn, only needed for this mode.
    from generation.multi_jd_compare import (
        print_multi_jd_summary,
        run_multi_jd_comparison,
    )

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
    parsed_jds: dict[str, dict] = {}

    for jd_file in jd_files:
        print(f"\n[Stage 1+2] Processing JD: {jd_file.name}")
        jd = parse_jd(jd_file.read_text(encoding="utf-8", errors="ignore"))
        print(f"  → {jd.get('title', '?')} @ {jd.get('company', '?')}")
        scored = score_resume(resume, jd)
        label = jd_file.stem
        parsed_jds[label] = jd
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

    # Always generate a PDF for the best-matching JD in multi mode.
    assembled = assemble_resume(
        scored_outputs[best_jd_label], parsed_jds[best_jd_label], resume=resume
    )
    if args.add_missing_skills:
        _print_injected(inject_missing_skills(assembled, assembled["gap_report"]))
    pdf_path = _stage3_generate(assembled, output_dir, f"best_match_{best_jd_label}")
    print(f"  Best-match PDF  : {pdf_path}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="resumeai",
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
    # Line-buffer stdout so print() and logging don't interleave, and force
    # UTF-8 so the box-drawing and check/cross glyphs below survive a non-UTF-8
    # console or a redirected pipe (cp1252 on Windows raises on them).
    # Done here rather than at import so importing cli.py has no side effects.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

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
