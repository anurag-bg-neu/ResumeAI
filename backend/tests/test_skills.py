import pytest

from parsing.utils import canonical_skill, extract_skills, is_location_line, split_outside_parens


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Strong experience with Python.", {"Python"}),  # sentence-final period
        ("Go, Rust and REST APIs", {"Go", "Rust", "REST"}),
        ("Node.js, React.js, k8s", {"Node.js", "React", "Kubernetes"}),
        ("Apache Kafka and Apache Flink", {"Kafka", "Flink"}),
        ("C/C++ firmware", {"C", "C++"}),
    ],
)
def test_extract_skills_finds_canonical_names(text, expected):
    assert set(extract_skills(text)) == expected


@pytest.mark.parametrize(
    "text",
    [
        "go above and beyond for the rest of the team",  # lowercase English words
        "presented to C-suite execs",  # single letter inside a hyphenated word
    ],
)
def test_extract_skills_ignores_ordinary_words(text):
    assert extract_skills(text) == []


def test_longer_skill_claims_its_text():
    # "Oracle" inside "Oracle Cloud", "Spring" inside "Spring Boot"
    assert extract_skills("Oracle Cloud upgrades") == ["Oracle Cloud"]
    assert set(extract_skills("Spring Boot and React Native")) == {"Spring Boot", "React Native"}


@pytest.mark.parametrize(
    ("raw", "canon"),
    [
        ("React.js", "React"),
        ("Express.js", "Express"),
        ("LLMs", "LLM"),
        ("Pandas", "pandas"),
        ("REST APIs", "REST"),
        ("Golang", "Go"),
        ("Some Unknown Tool", "Some Unknown Tool"),
    ],
)
def test_canonical_skill(raw, canon):
    assert canonical_skill(raw) == canon


def test_split_outside_parens_keeps_parenthesised_lists():
    assert split_outside_parens("AWS (EC2, S3), Docker; Go") == ["AWS (EC2, S3)", "Docker", "Go"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Boston, MA", True),
        ("Boston, MA, USA", True),
        ("Pune, Maharashtra, India", True),
        ("Remote", True),
        ("Granite Bank", False),
        ("Software Development Engineer", False),
        ("Google, Inc.", False),
        ("C++, Python, Java", False),
    ],
)
def test_is_location_line(line, expected):
    assert is_location_line(line) is expected
