"""Feeds polled by the news crawler. Only sources that allow automated access are listed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    category: str  # news | exchange | regulator | aggregator
    fetch_text: bool = True  # fetch and extract the full article page


_NSE_RSS = "https://nsearchives.nseindia.com/content/RSS"
_GNEWS = "https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q="

FEEDS: tuple[Feed, ...] = (
    # Exchange filings (authoritative company events). Items are short; the link is usually a PDF.
    *(
        Feed(f"nse_{n.lower()}", f"{_NSE_RSS}/{n}.xml", "exchange", fetch_text=False)
        for n in (
            "Online_announcements",
            "Financial_Results",
            "Board_Meetings",
            "Corporate_action",
            "Insider_Trading",
            "Shareholding_Pattern",
            "Annual_Reports",
            "Circulars",
            "Daily_Buyback",
            "Offer_Documents",
        )
    ),
    # Regulators
    Feed("rbi_press", "https://www.rbi.org.in/pressreleases_rss.xml", "regulator"),
    Feed("sebi", "https://www.sebi.gov.in/sebirss.xml", "regulator"),
    # Financial press
    Feed("et_markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "news"),
    Feed("et_stocks", "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms", "news"),
    Feed("mint_markets", "https://www.livemint.com/rss/markets", "news"),
    Feed("mint_companies", "https://www.livemint.com/rss/companies", "news"),
    Feed("bs_markets", "https://www.business-standard.com/rss/markets-106.rss", "news"),
    Feed("bs_companies", "https://www.business-standard.com/rss/companies-101.rss", "news"),
    Feed("hbl_markets", "https://www.thehindubusinessline.com/markets/feeder/default.rss", "news"),
    Feed("hbl_companies", "https://www.thehindubusinessline.com/companies/feeder/default.rss", "news"),
    # Aggregator: headlines + publisher only (links are redirect wrappers).
    *(
        Feed(f"gnews_{slug}", _GNEWS + q, "aggregator", fetch_text=False)
        for slug, q in (
            ("nse", "NSE%20stock%20market"),
            ("sensex_nifty", "Sensex%20Nifty"),
            ("rbi_policy", "RBI%20monetary%20policy"),
            ("fii_dii", "FII%20DII%20flows%20India"),
            ("results", "quarterly%20results%20India%20company"),
        )
    ),
)
