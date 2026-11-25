from t2.news.store import item_id
from t2.news.tickers import build, tag

ROWS = [
    ("VGL", "Varvee Global Limited"),
    ("GLOBAL", "Global Education Limited"),
    ("RELIANCE", "Reliance Industries Limited"),
    ("IDEA", "Vodafone Idea Limited"),
    ("TCS", "Tata Consultancy Services Limited"),
    ("IT", "Some IT Company Limited"),
]
M = build(ROWS)


def test_matches_company_names_case_insensitively() -> None:
    assert tag("reliance industries posts record profit", M) == ["RELIANCE"]


def test_bare_symbols_only_in_capitals() -> None:
    assert tag("TCS wins a deal", M) == ["TCS"]
    assert tag("a good idea for investors", M) == []
    assert tag("IDEA shares jump", M) == ["IDEA"]


def test_ambiguous_symbols_are_not_matched_bare() -> None:
    assert tag("IT stocks fall", M) == []


def test_item_id_is_stable_and_whitespace_insensitive() -> None:
    assert item_id("https://x.com/a ") == item_id("https://x.com/a")


def test_all_caps_lines_use_names_not_bare_symbols() -> None:
    assert tag("VARVEE GLOBAL LIMITED - Ex-Date: 27-Nov-2026", M) == ["VGL"]
