"""
person3_generation — Resume Assembly and Generation package.

Public interface:
    from person3_generation.assembler       import assemble_resume
    from person3_generation.latex_generator import generate_resume_pdf
    from person3_generation.multi_jd_compare import run_multi_jd_comparison
"""

from .assembler import assemble_resume
from .latex_generator import generate_resume_pdf
from .multi_jd_compare import run_multi_jd_comparison

__all__ = ["assemble_resume", "generate_resume_pdf", "run_multi_jd_comparison"]
