import pytest
from conftest import SAMPLE_JDS

from parsing.jd_parser import parse_jd


@pytest.mark.parametrize(
    ("name", "title", "company"),
    [
        ("jd1.txt", "Software Engineer", "PayPal"),
        ("jd3.txt", "Backend Engineer Intern", "Tinder"),
        ("jd4.txt", "Software Engineer Intern", "Adobe"),
    ],
)
def test_title_and_company(name, title, company):
    jd = parse_jd((SAMPLE_JDS / name).read_text(encoding="utf-8"))
    assert (jd["title"], jd["company"]) == (title, company)


def test_header_line_title_company():
    jd = parse_jd("Senior Backend Engineer | Acme Corp\nRequirements:\n- 3+ years with Python and k8s\n"
                  "Nice to have: Kafka")
    assert (jd["title"], jd["company"]) == ("Senior Backend Engineer", "Acme Corp")
    assert jd["requirements"]["required_skills"] == ["Kubernetes", "Python"]
    assert jd["requirements"]["preferred_skills"] == ["Kafka"]
    assert jd["requirements"]["experience_years"] == 3


def test_terse_jd_still_yields_skills():
    jd = parse_jd("Python, Go")
    assert jd["requirements"]["required_skills"] == ["Go", "Python"]
    assert jd["requirements"]["requirement_sentences"] == []


def test_raw_text_is_the_input():
    text = "Backend  Engineer  Python"
    assert parse_jd(text)["raw_text"] == text
