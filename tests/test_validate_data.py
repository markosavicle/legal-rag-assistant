from datetime import date
from pathlib import Path

import psycopg
import pytest

from app.config import settings
from scripts.validate_data import (
    SQL_FILE, article_findings, contract_findings, cross_document_findings, document_type, extract_fields,
    invalid_dates, parse_sql_checks,
)

SAMPLES = Path(__file__).parent.parent / "samples"
ANA = (SAMPLES / "ugovor_o_radu_ana_jovic.txt").read_text(encoding="utf-8")
ANNEX = (SAMPLES / "aneks_ugovora_ana_jovic.txt").read_text(encoding="utf-8")
UPLOADED = date(2026, 10, 12)


def checks(findings) -> list[str]:
    return [f.check for f in findings]


def test_sql_file_parses_into_named_checks():
    parsed = parse_sql_checks(SQL_FILE.read_text(encoding="utf-8"))
    names = [name for name, *_ in parsed]
    assert len(names) == len(set(names)) >= 10
    assert all(query.upper().startswith(("SELECT", "WITH")) for *_, query in parsed)


def test_document_type():
    assert document_type(ANA) == "contract"
    assert document_type(ANNEX) == "annex"
    assert document_type("Члан 1.\nтекст\n" * 25) == "law"


def test_extract_contract_fields():
    fields = extract_fields(ANA)
    assert fields["signed"] == date(2026, 3, 15) and fields["start"] == date(2026, 4, 1)
    assert fields["employer"] == "Primer Softver d.o.o." and fields["pib"] == "100000001"
    assert fields["employee"] == "Ana Jović" and fields["position"] == "Backend developer"
    assert fields["salary"] == "180.000,00" and fields["leave_days"] == 22
    assert fields["probation_months"] == 3 and fields["notice_days"] == 30


def test_valid_contract_has_no_findings():
    assert contract_findings("ana.txt", "contract", extract_fields(ANA), UPLOADED) == []


def test_missing_fields_and_bad_pib():
    text = ANA.replace("PIB 100000001", "PIB 12345").replace("počinje sa radom", "radi od")
    found = contract_findings("ana.txt", "contract", extract_fields(text), UPLOADED)
    assert checks(found) == ["missing_contract_field", "invalid_pib"]
    assert "start" in found[0].message


def test_start_before_signing_and_signed_after_upload():
    text = ANA.replace("01.04.2026.", "01.02.2026.")
    assert "date_order" in checks(contract_findings("ana.txt", "contract", extract_fields(text), UPLOADED))
    assert "date_order" in checks(contract_findings("ana.txt", "contract", extract_fields(ANA), date(2026, 1, 1)))


def test_impossible_dates():
    assert checks(invalid_dates("x.txt", "Zaključen dana 31.02.2026. godine")) == ["invalid_date"]
    assert invalid_dates("x.txt", "Zaključen dana 28.02.2026. godine, iznos 180.000,00") == []
    fields = extract_fields(ANA.replace("15.03.2026.", "31.02.2026."))
    assert "invalid_date" in checks(contract_findings("ana.txt", "contract", fields, UPLOADED))


def test_terms_below_the_law():
    found = contract_findings("aneks.txt", "annex", extract_fields(ANNEX), UPLOADED)
    assert checks(found) == ["conflicts_with_law"] and "20 working days" in found[0].message
    fields = extract_fields(ANA.replace("tri meseca", "sedam meseci"))
    assert any("probation" in f.message for f in contract_findings("a", "contract", fields, UPLOADED))


def test_annex_pointing_at_a_contract_date_that_does_not_exist():
    docs = [{"filename": "ana.txt", "kind": "contract", "fields": extract_fields(ANA)},
            {"filename": "aneks.txt", "kind": "annex", "fields": extract_fields(ANNEX)}]
    found = cross_document_findings(docs)
    assert checks(found) == ["annex_date_mismatch"] and "2025-03-15" in found[0].message
    fixed = extract_fields(ANNEX.replace("15.03.2025.", "15.03.2026."))
    assert cross_document_findings([docs[0], {**docs[1], "fields": fixed}]) == []


def test_one_employer_one_pib():
    other = extract_fields(ANA.replace("100000001", "100000009"))
    docs = [{"filename": "a", "kind": "contract", "fields": extract_fields(ANA)},
            {"filename": "b", "kind": "contract", "fields": other}]
    assert "inconsistent_pib" in checks(cross_document_findings(docs))


def test_article_gaps_and_repeats():
    chunks = ["Član 1.\nTekst.", "Član 2.\nTekst.", "Član 2. (nastavak)\nTekst.", "Član 4. *\nTekst.", "Član 2.\nPrelazna odredba."]
    found = article_findings("zakon.pdf", chunks)
    assert checks(found) == ["article_gaps", "repeated_article"]
    assert found[0].message.endswith(": 3") and found[1].message.endswith(": 2")


# --- SQL checks against a real database, on rows inserted in a rolled-back transaction ---------


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(settings.database_url, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("database not available")
    if connection.execute("SELECT to_regclass('chunks')").fetchone()[0] is None:
        pytest.skip("schema not created")
    yield connection
    connection.rollback()
    connection.close()


def run(conn, name: str) -> list:
    query = next(q for n, _, _, q in parse_sql_checks(SQL_FILE.read_text(encoding="utf-8")) if n == name)
    return conn.execute(query, {"embedding_model": settings.embedding_model}).fetchall()


def test_sql_checks_find_planted_problems(conn):
    dim = int(conn.execute("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                           "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'").fetchone()[0][7:-1])
    zero, one = "[" + ",".join(["0"] * dim) + "]", "[" + ",".join(["1"] * dim) + "]"
    ids = [conn.execute("INSERT INTO documents (filename, file_hash) VALUES ('test_copy.pdf', %s) RETURNING id",
                        (c * 64,)).fetchone()[0] for c in "ab"]
    rows = [(ids[0], 0, 1, "Član 1.\nIsti tekst u obe kopije dokumenta.", one),
            (ids[0], 2, None, "7", zero),  # chunk 1 missing, no page, tiny, zero vector
            (ids[1], 0, 1, "Član 1.\nIsti tekst u obe kopije dokumenta.", one),
            (ids[1], 1, None, "7", zero)]
    for doc, index, page, text, emb in rows:
        conn.execute("INSERT INTO chunks (document_id, chunk_index, page, content, search_text, stems, embedding) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s::vector)", (doc, index, page, text, text, text, emb))
    for name in ("duplicate_filename", "duplicate_document_content", "near_duplicate_documents", "tiny_chunks",
                 "chunk_index_gaps", "pdf_chunk_without_page", "zero_embeddings"):
        assert run(conn, name), name
