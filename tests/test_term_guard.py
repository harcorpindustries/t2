import base64

from tools.term_guard import find


def _term(i: int) -> str:
    return base64.b64decode(("Y2xhdWRl", "YW50aHJvcGlj", "b3B1cw==")[i]).decode()


def test_detects_each_term_case_insensitively() -> None:
    for i in range(3):
        assert find(f"x {_term(i).upper()} y")


def test_clean_text_passes() -> None:
    assert not find("feat: add nse bhavcopy collector")
