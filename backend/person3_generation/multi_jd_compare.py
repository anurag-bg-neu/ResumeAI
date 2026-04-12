"""
multi_jd_compare.py
-------------------
Stage 3 — Multi-JD Comparison Feature.

Runs one master resume against multiple JDs and produces:
  1. A score matrix (bullets × JDs) as a pandas DataFrame
  2. Classification of bullets into:
       - Universal  : high average score (>= 0.55) across all JDs
       - Role-specific: high (>= 0.50) for a subset but low (<= 0.30) elsewhere
       - Weak       : low (<= 0.35) average across all JDs
  3. A heatmap PNG via seaborn / matplotlib

Public API:
    from person3_generation.multi_jd_compare import run_multi_jd_comparison
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────

UNIVERSAL_THRESHOLD: float = 0.55   # avg across JDs → "universal"
ROLE_SPECIFIC_MIN: float = 0.50     # high for some JDs
ROLE_SPECIFIC_MAX: float = 0.30     # low for others
WEAK_THRESHOLD: float = 0.35        # avg across JDs → "weak"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _truncate(text: str, max_len: int = 55) -> str:
    return text[:max_len] + "…" if len(text) > max_len else text


def _collect_all_bullets(scored_output: dict) -> list[str]:
    """Flatten all bullet texts from experience + projects into one ordered list."""
    bullets: list[str] = []
    for section in ["experience", "projects"]:
        for entry in scored_output.get("scored_sections", {}).get(section, []):
            for b in entry.get("bullets", []):
                if b.get("text"):
                    bullets.append(b["text"])
    return bullets


def _get_bullet_score(bullet_text: str, scored_output: dict) -> float:
    """Look up the semantic_score for a bullet text in a scored output."""
    for section in ["experience", "projects"]:
        for entry in scored_output.get("scored_sections", {}).get(section, []):
            for b in entry.get("bullets", []):
                if b.get("text") == bullet_text:
                    return float(b.get("semantic_score", 0.0))
    return 0.0


def _classify_bullet(row: pd.Series) -> str:
    """Classify a bullet's row in the score matrix."""
    avg = row.mean()
    if avg >= UNIVERSAL_THRESHOLD:
        return "Universal"
    if avg <= WEAK_THRESHOLD:
        return "Weak"
    # Role-specific: at least one JD high and at least one JD low
    if row.max() >= ROLE_SPECIFIC_MIN and row.min() <= ROLE_SPECIFIC_MAX:
        return "Role-Specific"
    return "Moderate"


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def run_multi_jd_comparison(
    scored_outputs: dict[str, dict],
    output_dir: str = "results",
    heatmap_filename: str = "multi_jd_heatmap.png",
) -> dict:
    """
    Compare one resume across multiple scored outputs (one per JD).

    Args:
        scored_outputs: {jd_label: scored_output_dict, ...}
                        scored_output_dict is the output of score_resume().
        output_dir:     Directory to save the heatmap PNG.
        heatmap_filename: Filename for the heatmap image.

    Returns:
        {
          "score_matrix":     pd.DataFrame (bullets × JDs),
          "bullet_analysis":  pd.DataFrame (bullet, avg_score, classification),
          "universal":        [str],
          "role_specific":    [str],
          "weak":             [str],
          "heatmap_path":     str  (absolute path to PNG, or "" if write failed)
        }
    """
    if not scored_outputs:
        return {
            "score_matrix": pd.DataFrame(),
            "bullet_analysis": pd.DataFrame(),
            "universal": [],
            "role_specific": [],
            "weak": [],
            "heatmap_path": "",
        }

    # Collect union of all bullet texts across all scored outputs
    all_bullets_set: list[str] = []
    seen: set[str] = set()

    # Use the first scored_output to define bullet order (consistent ordering)
    first_scored = next(iter(scored_outputs.values()))
    for bullet in _collect_all_bullets(first_scored):
        if bullet not in seen:
            all_bullets_set.append(bullet)
            seen.add(bullet)

    # Build score matrix: rows = bullets, columns = JD labels
    jd_labels = list(scored_outputs.keys())
    matrix_data: dict[str, list[float]] = {}

    for label in jd_labels:
        scored = scored_outputs[label]
        matrix_data[label] = [_get_bullet_score(b, scored) for b in all_bullets_set]

    score_matrix = pd.DataFrame(matrix_data, index=[_truncate(b) for b in all_bullets_set])
    score_matrix.index.name = "Bullet"

    # Bullet classification
    avg_scores = score_matrix.mean(axis=1)
    classifications = score_matrix.apply(_classify_bullet, axis=1)

    bullet_analysis = pd.DataFrame({
        "bullet_text": [_truncate(b) for b in all_bullets_set],
        "avg_score": avg_scores.values.round(4),
        "classification": classifications.values,
    })
    bullet_analysis = bullet_analysis.sort_values("avg_score", ascending=False).reset_index(drop=True)

    universal = bullet_analysis.loc[
        bullet_analysis["classification"] == "Universal", "bullet_text"
    ].tolist()
    role_specific = bullet_analysis.loc[
        bullet_analysis["classification"] == "Role-Specific", "bullet_text"
    ].tolist()
    weak = bullet_analysis.loc[
        bullet_analysis["classification"] == "Weak", "bullet_text"
    ].tolist()

    log.info(
        "Multi-JD comparison: %d bullets × %d JDs | "
        "universal=%d, role-specific=%d, weak=%d",
        len(all_bullets_set), len(jd_labels),
        len(universal), len(role_specific), len(weak),
    )

    # Generate heatmap
    heatmap_path = ""
    try:
        heatmap_path = _save_heatmap(score_matrix, output_dir, heatmap_filename)
    except Exception as exc:
        log.warning("Heatmap generation failed: %s", exc)

    return {
        "score_matrix": score_matrix,
        "bullet_analysis": bullet_analysis,
        "universal": universal,
        "role_specific": role_specific,
        "weak": weak,
        "heatmap_path": heatmap_path,
    }


def _save_heatmap(
    score_matrix: pd.DataFrame,
    output_dir: str,
    filename: str,
) -> str:
    """
    Save a seaborn heatmap of bullet × JD semantic scores.

    Returns the absolute path to the saved PNG.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_path = out_dir / filename

    n_bullets, n_jds = score_matrix.shape
    fig_height = max(6, n_bullets * 0.35)
    fig_width = max(8, n_jds * 1.8)

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    sns.heatmap(
        score_matrix,
        annot=True,
        fmt=".2f",
        cmap="RdYlGn",
        vmin=0.0,
        vmax=1.0,
        linewidths=0.3,
        linecolor="white",
        cbar_kws={"label": "Semantic Score", "shrink": 0.6},
        ax=ax,
    )

    ax.set_title("Resume Bullet × JD Semantic Score Heatmap", fontsize=13, pad=14)
    ax.set_xlabel("Job Description", fontsize=10)
    ax.set_ylabel("Resume Bullet", fontsize=10)
    ax.tick_params(axis="x", labelsize=8, rotation=25)
    ax.tick_params(axis="y", labelsize=7, rotation=0)

    plt.tight_layout()
    fig.savefig(str(save_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    log.info("Heatmap saved to: %s", save_path)
    return str(save_path.resolve())


def print_multi_jd_summary(results: dict) -> None:
    """Pretty-print the multi-JD comparison summary to stdout."""
    SEP = "=" * 72

    print(f"\n{SEP}")
    print("  MULTI-JD COMPARISON SUMMARY")
    print(SEP)

    ba: pd.DataFrame = results.get("bullet_analysis", pd.DataFrame())
    if ba.empty:
        print("  (no data)")
        return

    print(f"\n  {'Classification':<16} {'Avg Score':>10}  {'Bullet (truncated)'}")
    print(f"  {'---------------':<16} {'---------':>10}  {'-------------------'}")
    for _, row in ba.iterrows():
        print(f"  {row['classification']:<16} {row['avg_score']:>10.4f}  {row['bullet_text']}")

    print(f"\n  Universal bullets  ({len(results['universal'])}): strongest across all JDs")
    for b in results["universal"]:
        print(f"    ✓ {b}")

    print(f"\n  Role-specific bullets ({len(results['role_specific'])}): tailor per application")
    for b in results["role_specific"]:
        print(f"    ~ {b}")

    print(f"\n  Weak bullets ({len(results['weak'])}): consider rewriting or removing")
    for b in results["weak"]:
        print(f"    ✗ {b}")

    if results.get("heatmap_path"):
        print(f"\n  Heatmap saved to: {results['heatmap_path']}")

    print(f"\n{SEP}\n")
