"""
generation — Stage 3: tailored resume assembly and PDF generation.

Public interface:
    from generation import assemble_resume, inject_missing_skills, generate_resume_pdf

Note: run_multi_jd_comparison is deliberately NOT re-exported here. It pulls
pandas/matplotlib/seaborn at import time, and it is only used by the CLI's
--multi-jd mode. Import it directly from generation.multi_jd_compare so the
API process never pays for the plotting stack.
"""

from .assembler import assemble_resume, inject_missing_skills
from .pdf_generator import generate_resume_pdf

__all__ = ["assemble_resume", "inject_missing_skills", "generate_resume_pdf"]
