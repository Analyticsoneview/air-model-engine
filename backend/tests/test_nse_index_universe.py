import csv
import io

from app.nse_index_universe import (
    INDEX_SOURCES, NSEIndexUniverseStore, parse_constituents,
)


def make_csv(count, prefix="S"):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Symbol", "Company Name", "ISIN Code"])
    writer.writeheader()
    for index in range(count):
        writer.writerow({"Symbol": f"{prefix}{index:03d}", "Company Name": f"Company {index}",
                         "ISIN Code": f"INE{index:09d}"})
    return output.getvalue()


def test_official_index_csv_parser_enforces_expected_membership_count():
    for code, config in INDEX_SOURCES.items():
        records = parse_constituents(make_csv(config["expected_count"], code), code)
        assert len(records) == config["expected_count"]
        assert records[0]["index_code"] == code


def test_official_index_csv_parser_fails_closed_on_wrong_count_and_duplicate():
    try:
        parse_constituents(make_csv(99), "NIFTY100")
    except ValueError as exc:
        assert "expected 100" in str(exc)
    else:
        raise AssertionError("wrong-sized constituent list must fail")
    duplicate = "Symbol,Company Name\nABC,Alpha\nABC,Alpha duplicate\n"
    try:
        parse_constituents(duplicate * 50, "NIFTY100")
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("duplicate constituent list must fail")


def test_registry_keeps_index_membership_and_returns_deduplicated_union(tmp_path):
    store = NSEIndexUniverseStore(str(tmp_path / "nse.sqlite3"))
    retrieved = "2026-11-16T12:00:00+00:00"
    for code, config in INDEX_SOURCES.items():
        records = parse_constituents(make_csv(config["expected_count"], "COMMON" if code == "NIFTY100" else code), code)
        store.save_snapshot(code, records, retrieved, config["url"])
    result = store.latest_universe()
    assert result["status"] == "READY"
    assert result["index_counts"] == {code: config["expected_count"] for code, config in INDEX_SOURCES.items()}
    assert result["unique_symbol_count"] == sum(config["expected_count"] for config in INDEX_SOURCES.values())
    assert result["constituents"][0]["index_memberships"]
