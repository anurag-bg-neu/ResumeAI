"""
test_api.py
-----------
Quick smoke-test for the ResumeAI API.

Usage:
    1. Start the API:   python -m uvicorn api.main:app --port 8000
    2. Run this script:  python test_api.py

Requires:  pip install requests
"""

import json
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests first:  pip install requests")
    sys.exit(1)

BASE = "http://localhost:8000"
RESUME = Path(__file__).parent / "data" / "sample_resumes" / "milan.pdf"
JD = Path(__file__).parent / "data" / "sample_jds" / "jd1.txt"


def main():
    # ── Health check ─────────────────────────────────────────────────────
    print("1. Health check...")
    r = requests.get(f"{BASE}/api/health", timeout=5)
    assert r.status_code == 200, f"Health check failed: {r.status_code}"
    print(f"   OK  {r.json()}")

    # ── Analyze ──────────────────────────────────────────────────────────
    if not RESUME.exists():
        print(f"\n   SKIP — sample resume not found at {RESUME}")
        print("   Place a PDF at data/sample_resumes/milan.pdf to run the full test.")
        return

    jd_text = JD.read_text() if JD.exists() else "Software Engineer at Google"

    print("\n2. Submitting resume + JD for analysis...")
    print(f"   Resume: {RESUME.name}  |  JD: {len(jd_text)} chars")
    with open(RESUME, "rb") as f:
        r = requests.post(
            f"{BASE}/api/analyze",
            files={"resume": (RESUME.name, f, "application/pdf")},
            data={"jd_text": jd_text},
            timeout=120,
        )

    if r.status_code != 200:
        print(f"   FAIL  status={r.status_code}")
        print(f"   {r.text[:500]}")
        return

    result = r.json()
    print(f"   OK  job_id={result['job_id']}")
    print(f"   Semantic score : {result['scores']['semantic']}")
    print(f"   Keyword score  : {result['scores']['keyword']}")
    print(f"   Skills covered : {len(result['skills_analysis']['covered'])}")
    print(f"   Skills missing : {len(result['skills_analysis']['missing'])}")
    print(f"   Experiences    : {result['experience_count']}")
    print(f"   Projects       : {result['project_count']}")

    # ── Download PDF ─────────────────────────────────────────────────────
    print(f"\n3. Downloading tailored PDF (job_id={result['job_id']})...")
    r = requests.get(f"{BASE}/api/download/{result['job_id']}", timeout=30)
    if r.status_code == 200:
        out = Path("test_output.pdf")
        out.write_bytes(r.content)
        print(f"   OK  saved to {out}  ({len(r.content)} bytes)")
    else:
        print(f"   FAIL  status={r.status_code}")

    # ── Full JSON dump for inspection ────────────────────────────────────
    print("\n4. Full API response:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
