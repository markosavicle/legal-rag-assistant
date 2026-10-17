"""Data-validation checks on the ingested documents: duplicates, missing fields, inconsistent dates.

Two layers:

  SQL      scripts/data_checks.sql: duplicates (files, documents, chunks), missing or empty fields,
           broken chunk numbering, PDF chunks without pages, zero embeddings, impossible timestamps.
  Python   checks that need parsing: derived search fields out of sync with the text, invalid
           calendar dates, contracts and annexes missing key fields (parties, PIB, dates, salary),
           dates in the wrong order, an annex pointing at a contract date that does not exist,
           contract terms below the legal minimums of the Labour Law, and gaps in article numbering.

Exits with status 1 when any error is found, so it can gate CI or a bulk ingest.

Usage: python -m scripts.validate_data [--out eval/data_validation.json]
"""
import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from app import db
from app.config import settings
from app.stemmer import stem_text
from app.text import for_search

SQL_FILE = Path(__file__).with_name("data_checks.sql")
SEVERITIES = ("error", "warning", "info")


@dataclass
class Finding:
    check: str
    severity: str
    message: str
    rows: list = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# SQL checks
# ---------------------------------------------------------------------------------------------

_HEADER = re.compile(r"^-- name:\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(.+)$", re.MULTILINE)


def parse_sql_checks(sql: str) -> list[tuple[str, str, str, str]]:
    """(name, severity, description, query) for every `-- name:` block in the file."""
    headers = list(_HEADER.finditer(sql))
    checks = []
    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(sql)
        query = "\n".join(l for l in sql[h.end():end].splitlines() if not l.strip().startswith("--")).strip().rstrip(";")
        if h.group(2) not in SEVERITIES:
            raise ValueError(f"{h.group(1)}: unknown severity {h.group(2)!r}")
        checks.append((h.group(1), h.group(2), h.group(3).strip(), query))
    return checks


def run_sql_checks(conn) -> tuple[list[Finding], list[str]]:
    findings, passed = [], []
    for name, severity, description, query in parse_sql_checks(SQL_FILE.read_text(encoding="utf-8")):
        cur = conn.execute(query, {"embedding_model": settings.embedding_model})
        columns = [c.name for c in cur.description]
        rows = [dict(zip(columns, map(_plain, row))) for row in cur.fetchall()]
        if rows:
            findings.append(Finding(name, severity, f"{len(rows)} row(s): {description}", rows))
        else:
            passed.append(name)
    return findings, passed


def _plain(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


# ---------------------------------------------------------------------------------------------
# Parsing documents
# ---------------------------------------------------------------------------------------------

DATE = r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\."
_ANY_DATE = re.compile(r"(?<![\d.])(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b")
_WORD_NUMBERS = {"jedan": 1, "jednog": 1, "dva": 2, "dve": 2, "tri": 3, "četiri": 4, "pet": 5, "šest": 6,
                 "sedam": 7, "osam": 8, "devet": 9, "deset": 10, "jedanaest": 11, "dvanaest": 12}

FIELDS = {
    "signed": rf"Zaključen dana {DATE}",
    "start": rf"počinje sa radom {DATE}",
    "effective": rf"(?:Počev od|stupa na snagu) {DATE}",
    "base_contract": rf"menja se Ugovor o radu zaključen\D*?dana {DATE}",
    "employer": r"Poslodavca:\s*([^,\n]+)",
    "pib": r"\bPIB\s*(\d+)",
    "employee": r"Zaposlen(?:a|og|i|e):\s*(.+?)\s+iz\b",
    "position": r"radnog mesta\s+([^.\n]+)",
    "salary": r"zarada[^.]*?iznosi\s+([\d.]+,\d{2})\s+dinara",
    "leave_days": r"godišnji odmor u trajanju od (\d+) radn",
    "probation_months": r"probni rad u trajanju od (\w+) mesec",
    "fixed_term_months": r"na određeno vreme od (\w+) mesec",
    "notice_days": r"Otkazni rok u slučaju otkaza od strane Zaposlen\w*\s+iznosi (\d+) dana",
}
REQUIRED = {
    "contract": ("signed", "start", "employer", "pib", "employee", "position", "salary"),
    "annex": ("signed", "effective", "base_contract", "employer", "pib", "employee"),
}
# Zakon o radu: probni rad najduže šest meseci (čl. 36), određeno vreme najduže 24 meseca (čl. 37),
# godišnji odmor najmanje 20 radnih dana (čl. 69), otkazni rok zaposlenog najviše 30 dana (čl. 178).
LEGAL_LIMITS = {
    "probation_months": (None, 6, "probation longer than the legal maximum of 6 months (čl. 36)"),
    "fixed_term_months": (None, 24, "fixed-term contract longer than the legal maximum of 24 months (čl. 37)"),
    "leave_days": (20, None, "annual leave below the legal minimum of 20 working days (čl. 69)"),
    "notice_days": (15, 30, "employee notice period outside the legal 15-30 days (čl. 178)"),
}


def document_type(text: str) -> str:
    text = for_search(text)
    head = text[:200].upper()
    if head.startswith("ANEKS"):
        return "annex"
    if head.startswith("UGOVOR O RADU"):
        return "contract"
    return "law" if len(re.findall(r"^Član \d+", text, re.MULTILINE)) >= 20 else "other"


def parse_date(groups) -> date | None:
    day, month, year = map(int, groups)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _number(value: str) -> int | None:
    return int(value) if value.isdigit() else _WORD_NUMBERS.get(value.lower())


def extract_fields(text: str) -> dict:
    """Key fields of a contract or annex, from its (Latin) text. Missing fields are left out."""
    text = for_search(text)
    found = {}
    for name, pattern in FIELDS.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        if name in ("signed", "start", "effective", "base_contract"):
            found[name] = parse_date(m.groups()) or f"invalid:{'.'.join(m.groups())}"
        elif name.endswith(("_days", "_months")):
            found[name] = _number(m.group(1))
        else:
            found[name] = m.group(1).strip()
    return found


# ---------------------------------------------------------------------------------------------
# Python checks
# ---------------------------------------------------------------------------------------------


def invalid_dates(filename: str, text: str) -> list[Finding]:
    bad = sorted({m.group(0) for m in _ANY_DATE.finditer(text) if parse_date(m.groups()) is None})
    return [Finding("invalid_date", "error", f"{filename}: date(s) that do not exist: {', '.join(bad)}")] if bad else []


def contract_findings(filename: str, kind: str, fields: dict, uploaded: date) -> list[Finding]:
    """Missing fields, date order and legal limits for one contract or annex."""
    out = []
    missing = [f for f in REQUIRED[kind] if f not in fields]
    if missing:
        out.append(Finding("missing_contract_field", "error", f"{filename}: no {', '.join(missing)} found"))
    if "pib" in fields and not re.fullmatch(r"\d{9}", fields["pib"]):
        out.append(Finding("invalid_pib", "error", f"{filename}: PIB {fields['pib']} is not 9 digits"))
    dates = {k: v for k, v in fields.items() if isinstance(v, date)}
    signed = dates.get("signed")
    for name, later in (("start", dates.get("start")), ("effective", dates.get("effective"))):
        if signed and later and later < signed:
            out.append(Finding("date_order", "error", f"{filename}: {name} date {later} is before the signing date {signed}"))
    if signed and dates.get("start") and (dates["start"] - signed).days > 366:
        out.append(Finding("date_order", "warning", f"{filename}: work starts more than a year after signing"))
    if signed and signed > uploaded:
        out.append(Finding("date_order", "warning", f"{filename}: signed on {signed}, after it was uploaded ({uploaded})"))
    for name in ("signed", "start", "effective", "base_contract"):
        if str(fields.get(name, "")).startswith("invalid:"):
            out.append(Finding("invalid_date", "error", f"{filename}: {name} date {fields[name][8:]} does not exist"))
    for name, (low, high, message) in LEGAL_LIMITS.items():
        value = fields.get(name)
        if value is not None and ((low is not None and value < low) or (high is not None and value > high)):
            out.append(Finding("conflicts_with_law", "error", f"{filename}: {message}; the document says {value}"))
    return out


def cross_document_findings(docs: list[dict]) -> list[Finding]:
    """Annexes must point at an indexed contract of the same employee, with that contract's date;
    one employer must have one PIB."""
    out = []
    contracts = [d for d in docs if d["kind"] == "contract"]
    for annex in (d for d in docs if d["kind"] == "annex"):
        f = annex["fields"]
        same_employee = [c for c in contracts if c["fields"].get("employee") == f.get("employee")]
        if not same_employee:
            out.append(Finding("annex_without_contract", "warning",
                               f"{annex['filename']}: no indexed contract for {f.get('employee')}"))
            continue
        for contract in same_employee:
            base, signed = f.get("base_contract"), contract["fields"].get("signed")
            if isinstance(base, date) and isinstance(signed, date) and base != signed:
                out.append(Finding("annex_date_mismatch", "error",
                                   f"{annex['filename']}: amends the contract of {base}, but {contract['filename']} "
                                   f"was signed on {signed}"))
            annex_signed = f.get("signed")
            if isinstance(annex_signed, date) and isinstance(signed, date) and annex_signed < signed:
                out.append(Finding("date_order", "error",
                                   f"{annex['filename']}: signed on {annex_signed}, before the contract it amends ({signed})"))
    pibs: dict[str, set] = {}
    for d in docs:
        if d["fields"].get("employer") and d["fields"].get("pib"):
            pibs.setdefault(d["fields"]["employer"], set()).add(d["fields"]["pib"])
    for employer, values in pibs.items():
        if len(values) > 1:
            out.append(Finding("inconsistent_pib", "error", f"{employer} appears with different PIBs: {sorted(values)}"))
    return out


_ARTICLE = re.compile(r"^Član (\d+)([a-z]?)\.?\s*(\(nastavak\))?", re.MULTILINE)


def article_findings(filename: str, chunk_texts: list[str]) -> list[Finding]:
    """A law is numbered 1..N. A missing number means text was lost in extraction; a number that
    starts two chunks (other than continuations) means an article was stored twice."""
    starts = []
    for text in chunk_texts:
        m = _ARTICLE.match(for_search(text))
        if m and not m.group(3):
            starts.append(f"{m.group(1)}{m.group(2)}")
    numbers = {int(re.match(r"\d+", s).group(0)) for s in starts}
    out = []
    if numbers:
        gaps = sorted(set(range(1, max(numbers) + 1)) - numbers)
        if gaps:
            out.append(Finding("article_gaps", "warning",
                               f"{filename}: {len(gaps)} article number(s) never start a chunk: {_ranges(gaps)}"))
    repeated = sorted({s for s in starts if starts.count(s) > 1}, key=lambda s: (int(re.match(r'\d+', s).group(0)), s))
    if repeated:
        out.append(Finding("repeated_article", "warning", f"{filename}: article heading(s) start more than one chunk: {', '.join(repeated)}"))
    return out


def _ranges(numbers: list[int]) -> str:
    parts, start = [], None
    for i, n in enumerate(numbers):
        start = n if start is None else start
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            parts.append(str(start) if start == n else f"{start}-{n}")
            start = None
    return ", ".join(parts)


def run_python_checks(conn) -> list[Finding]:
    findings, docs = [], []
    documents = conn.execute("SELECT id, filename, created_at FROM documents ORDER BY id").fetchall()
    for doc_id, filename, created_at in documents:
        chunks = conn.execute(
            "SELECT chunk_index, content, search_text, stems FROM chunks WHERE document_id = %s ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()
        stale = [i for i, content, search_text, stems in chunks
                 if search_text != for_search(content) or stems != stem_text(search_text)]
        if stale:
            findings.append(Finding("stale_search_fields", "error",
                                    f"{filename}: {len(stale)} chunk(s) whose search text or stems do not match their content "
                                    f"(re-index): {stale[:10]}"))
        text = "\n".join(content for _, content, _, _ in chunks)
        findings += invalid_dates(filename, for_search(text))
        kind = document_type(text)
        if kind in ("contract", "annex"):
            fields = extract_fields(text)
            docs.append({"filename": filename, "kind": kind, "fields": fields})
            findings += contract_findings(filename, kind, fields, created_at.date())
        elif kind == "law":
            findings += article_findings(filename, [content for _, content, _, _ in chunks])
    return findings + cross_document_findings(docs)


# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="write the findings as JSON")
    parser.add_argument("--rows", type=int, default=3, help="example rows to print per SQL finding")
    args = parser.parse_args()

    with db.connect() as conn:
        sql_findings, passed = run_sql_checks(conn)
        findings = sql_findings + run_python_checks(conn)
        documents, chunks = conn.execute("SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)").fetchone()

    findings.sort(key=lambda f: SEVERITIES.index(f.severity))
    print(f"{documents} documents, {chunks} chunks. SQL checks passed: {', '.join(passed) or 'none'}\n")
    for f in findings:
        print(f"{f.severity.upper():<8}{f.check:<28}{f.message}")
        for row in f.rows[: args.rows]:
            print(f"{'':36}{row}")
    counts = {s: sum(f.severity == s for f in findings) for s in SEVERITIES}
    print(f"\n{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info")
    if args.out:
        args.out.write_text(json.dumps({"documents": documents, "chunks": chunks, "passed_sql_checks": passed,
                                        "findings": [asdict(f) for f in findings]}, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
    sys.exit(1 if counts["error"] else 0)


if __name__ == "__main__":
    main()
