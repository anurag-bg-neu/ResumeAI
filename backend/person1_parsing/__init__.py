"""
person1_parsing — Resume and Job Description parsing package.

Public interface:
    from person1_parsing.resume_parser import parse_resume
    from person1_parsing.jd_parser    import parse_jd
"""

from .resume_parser import parse_resume
from .jd_parser import parse_jd

__all__ = ["parse_resume", "parse_jd"]
