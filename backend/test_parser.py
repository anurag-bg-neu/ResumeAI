"""
test_parser.py — ResumeAI · Parsing Layer:
Demonstrates how to use ResumeParser and JDParser independently.

Run:
    # Parse a real PDF resume
    python test_parser.py --resume data/sample_resumes/milan.pdf

    # Parse a JD file
    python test_parser.py --jd data/sample_jds/jd4.txt

    # Test both
    python test_parser.py -r data/sample_resumes/milan.pdf -j data/sample_jds/jd4.txt -v
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Import the public API from your package
try:
    from person1_parsing import parse_resume, parse_jd
except ImportError as e:
    print(f"Error importing package: {e}")
    print(
        "Ensure this script is placed directly outside the 'person1_parsing' directory."
    )
    sys.exit(1)


def main():
    # Set up command line arguments
    parser = argparse.ArgumentParser(
        description="Test runner for the ResumeAI parsing package."
    )
    parser.add_argument("-r", "--resume", type=str, help="Path to the resume PDF file.")
    parser.add_argument(
        "-j", "--jd", type=str, help="Path to the job description text file."
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable INFO logging output from the parsers.",
    )

    args = parser.parse_args()

    # Configure logging based on the verbose flag
    if args.verbose:
        logging.basicConfig(
            level=logging.INFO, format="%(name)s [%(levelname)s] %(message)s"
        )
    else:
        # Suppress everything below WARNING unless verbose is passed
        logging.basicConfig(level=logging.WARNING)

    if not args.resume and not args.jd:
        parser.print_help()
        print(
            "\nError: Please provide at least one file to parse (-r/--resume or -j/--jd)."
        )
        sys.exit(1)

    # 1. Parse Resume
    if args.resume:
        resume_path = Path(args.resume)
        if not resume_path.exists():
            print(f"Error: Resume file not found at '{resume_path}'")
        else:
            print(f"\n{'='*50}\nParsing Resume: {resume_path.name}\n{'='*50}")
            try:
                # Call the API
                resume_json = parse_resume(str(resume_path))
                # Pretty print the result
                print(json.dumps(resume_json, indent=2, ensure_ascii=False))
            except Exception as e:
                print(f"Failed to parse resume: {e}")

    # 2. Parse Job Description
    if args.jd:
        jd_path = Path(args.jd)
        if not jd_path.exists():
            print(f"Error: JD file not found at '{jd_path}'")
        else:
            print(f"\n{'='*50}\nParsing Job Description: {jd_path.name}\n{'='*50}")
            try:
                # Read the text file first, as parse_jd expects a string
                jd_text = jd_path.read_text(encoding="utf-8")
                # Call the API
                jd_json = parse_jd(jd_text)
                # Pretty print the result
                print(json.dumps(jd_json, indent=2, ensure_ascii=False))
            except Exception as e:
                print(f"Failed to parse JD: {e}")


if __name__ == "__main__":
    main()
