import io
import zipfile
from datetime import date

import polars as pl

from t2.data.collect_nse import LEDGER_SCHEMA, days_needing_work, merge
from t2.data.nse_archive import candidate_urls, parse_cm, parse_fo, parse_mto


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


def test_legacy_cm_without_isin_column() -> None:
    raw = _zip(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,\n"
        "ABB,EQ,715,715,715,715,715,0.0,100,71500,3-NOV-1994,\n"
    )
    df = parse_cm(raw, "legacy", date(1994, 11, 3))
    row = df.row(0, named=True)
    assert row["symbol"] == "ABB" and row["volume"] == 100 and row["isin"] is None
    assert row["date"] == date(1994, 11, 3)


def test_udiff_and_legacy_fo_share_schema_and_units() -> None:
    legacy = _zip(
        "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,"
        "VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,\n"
        "FUTIDX,NIFTY,29-Jun-2000,0,XX,1461,1472,1451,1452.75,1451.15,62,181.2,4000,4000,12-JUN-2000,\n"
    )
    udiff = _zip(
        "TradDt,FinInstrmTp,TckrSymb,XpryDt,StrkPric,OptnTp,OpnPric,HghPric,LwPric,ClsPric,SttlmPric,"
        "TtlTradgVol,TtlTrfVal,OpnIntrst,ChngInOpnIntrst,UndrlygPric,NewBrdLotQty,TtlNbOfTxsExctd\n"
        "2026-11-25,STO,ABCAPITAL,2026-12-29,425.00,PE,13.85,15.85,12.40,14.75,14.75,303,206220602.50,"
        "113150,58900,422.00,1550,275\n"
    )
    a = parse_fo(legacy, "legacy", date(2000, 6, 12))
    b = parse_fo(udiff, "udiff", date(2026, 11, 25))
    assert a.schema == b.schema
    ra, rb = a.row(0, named=True), b.row(0, named=True)
    assert ra["strike"] is None and ra["option_type"] is None  # futures normalized
    assert ra["turnover"] == 181.2 * 1e5  # lakhs -> rupees
    assert rb["instrument"] == "OPTSTK" and rb["expiry"] == date(2026, 12, 29) and rb["lot_size"] == 1550


def test_mto_parses_only_security_records() -> None:
    raw = (
        b"Security Wise Delivery Position - Compulsory Rolling Settlement\n"
        b"10,MTO,02012015,325859130,0001536\n"
        b"Record Type,Sr No,Name of Security,Quantity Traded,Deliverable Quantity,% of Deliverable\n"
        b"20,1,20MICRONS,EQ,76443,50983,66.69\n"
    )
    df = parse_mto(raw, date(2015, 1, 2))
    assert df.height == 1 and df.row(0, named=True)["deliverable_pct"] == 66.69


def test_candidate_urls_try_udiff_then_legacy() -> None:
    urls = candidate_urls("cm", date(2015, 1, 2))
    assert [f for f, _ in urls] == ["udiff", "legacy"]
    assert urls[1][1].endswith("/EQUITIES/2015/JAN/cm02JAN2015bhav.csv.zip")


def _ledger(rows: list[tuple[date, str, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        [{**dict.fromkeys(LEDGER_SCHEMA), "date": d, "kind": k, "status": s} for d, k, s in rows],
        schema=LEDGER_SCHEMA,
    )


def test_merge_never_downgrades_ok() -> None:
    d = date(2020, 1, 2)
    merged = merge(_ledger([(d, "cm", "ok")]), _ledger([(d, "cm", "error")]))
    assert merged["status"].to_list() == ["ok"]
    merged = merge(_ledger([(d, "cm", "error")]), _ledger([(d, "cm", "ok")]))
    assert merged["status"].to_list() == ["ok"]


def test_recent_not_published_is_rechecked_old_is_final() -> None:
    today = date(2026, 11, 26)
    recent, old = date(2026, 11, 24), date(2026, 11, 1)
    rows = [(d, k, "not_published") for d in (recent, old) for k in ("cm", "fo", "mto")]
    todo = days_needing_work(_ledger(rows), [old, recent], today)
    assert todo == [recent]


def test_errors_are_always_retried() -> None:
    d = date(2010, 5, 5)
    rows = [(d, "cm", "ok"), (d, "fo", "error"), (d, "mto", "ok")]
    assert days_needing_work(_ledger(rows), [d], date(2026, 11, 26)) == [d]
