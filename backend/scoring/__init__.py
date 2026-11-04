"""
scoring — Stage 2: resume/JD relevance scoring and skill gap analysis.

Public interface:
    from scoring import score_resume
"""

from .scorer import score_resume

__all__ = ["score_resume"]
