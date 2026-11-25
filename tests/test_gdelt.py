from datetime import UTC, datetime

from t2.news.gdelt import domain_kind, month_files, parse_rows, slug_title


def _row(domain: str, locations: str = "", extras: str = "") -> str:
    cols = [""] * 27
    cols[0], cols[1], cols[3], cols[4] = (
        "id1",
        "20160615060000",
        domain,
        f"https://{domain}/markets/sensex-rallies-on-rate-cut-hopes-116061500123_1.html",
    )
    cols[9], cols[13], cols[15], cols[26] = (
        locations,
        "reserve bank of india,10;tata motors,40",
        "-1.5,2.0,3.5,5.5,20,1,412",
        extras,
    )
    return "\t".join(cols)


def test_domain_matching_is_exact() -> None:
    assert domain_kind("business-standard.com") == "finance"
    assert domain_kind("m.economictimes.indiatimes.com") == "finance"
    assert domain_kind("thefinancialexpress-bd.com") is None
    assert domain_kind("reuters.com") == "wire"


def test_wires_kept_only_when_about_india_economy() -> None:
    def wire(loc: str, themes: str) -> str:
        cols = _row("reuters.com", loc).split("\t")
        cols[7] = themes
        return "\t".join(cols)

    rows, total = parse_rows(
        "\n".join(
            [
                wire("1#India#IN#IN", "ECON_STOCKMARKET;TAX_FNCACT"),
                wire("1#India#IN#IN", "HEALTH_PANDEMIC"),
                wire("1#France#FR#FR", "ECON_STOCKMARKET"),
            ]
        )
    )
    assert total == 3 and len(rows) == 1


def test_title_from_page_or_url_slug() -> None:
    rows, _ = parse_rows(_row("business-standard.com", extras="<PAGE_TITLE>Sensex rallies</PAGE_TITLE>"))
    assert rows[0]["title"] == "Sensex rallies" and rows[0]["title_source"] == "page"
    rows, _ = parse_rows(_row("business-standard.com"))
    assert rows[0]["title"] == "Sensex rallies on rate cut hopes" and rows[0]["title_source"] == "url_slug"
    assert rows[0]["organizations"] == ["reserve bank of india", "tata motors"]
    assert rows[0]["tone"] == -1.5 and rows[0]["word_count"] == 412


def test_slug_title_strips_ids() -> None:
    assert (
        slug_title("https://economictimes.indiatimes.com/markets/stocks/news/nifty-ends-higher/articleshow/123.cms")
        == "Nifty ends higher"
    )


def test_month_files_every_15_minutes_and_not_future() -> None:
    files = month_files("2016-06", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert len(files) == 30 * 96 and files[0] == "20160601000000" and files[1] == "20160601001500"
    assert month_files("2015-02")[0] == "20150218230000"
