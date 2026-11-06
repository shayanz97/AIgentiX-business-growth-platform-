"""CSV company import: parsing, validation and in-file deduplication (pure; no database access)."""

import csv
import io
from dataclasses import dataclass, field

from aigentix.modules.lead_intelligence.domain.domains import InvalidWebsite, parse_website

NAME_HEADERS = ("name", "company", "company name", "company_name")
URL_HEADERS = ("website", "url", "website url", "website_url", "domain", "homepage")
MAX_NAME_LENGTH = 200


class CsvFormatError(ValueError):
    """The file as a whole cannot be processed."""


@dataclass
class CsvRow:
    line: int
    name: str
    website_url: str | None = None
    canonical_domain: str | None = None
    errors: list[str] = field(default_factory=list)
    duplicate_of_line: int | None = None

    @property
    def valid(self) -> bool:
        return not self.errors and self.duplicate_of_line is None


def _header_index(header: list[str], candidates: tuple[str, ...]) -> int | None:
    normalised = [h.strip().lower().lstrip("﻿") for h in header]
    for i, h in enumerate(normalised):
        if h in candidates:
            return i
    return None


def parse_company_csv(text: str, *, max_rows: int, max_bytes: int) -> list[CsvRow]:
    if len(text.encode("utf-8")) > max_bytes:
        raise CsvFormatError(f"File is larger than {max_bytes // 1024} KB")
    if "\x00" in text:
        raise CsvFormatError("File does not look like a text CSV")
    try:
        sample = text[:4096]
        dialect: type[csv.Dialect] = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise CsvFormatError("File is empty") from exc
    except csv.Error as exc:
        raise CsvFormatError("File is not valid CSV") from exc
    name_i = _header_index(header, NAME_HEADERS)
    url_i = _header_index(header, URL_HEADERS)
    if name_i is None and url_i is None:
        raise CsvFormatError("Header row must contain a 'name' and/or 'website' column")

    rows: list[CsvRow] = []
    seen: dict[str, int] = {}
    try:
        for line_no, record in enumerate(reader, start=2):
            if not any(cell.strip() for cell in record):
                continue
            if len(rows) >= max_rows:
                raise CsvFormatError(f"Too many rows: the maximum is {max_rows} companies per import")
            name = record[name_i].strip() if name_i is not None and name_i < len(record) else ""
            url = record[url_i].strip() if url_i is not None and url_i < len(record) else ""
            row = CsvRow(line=line_no, name=name[:MAX_NAME_LENGTH])
            if len(name) > MAX_NAME_LENGTH:
                row.errors.append(f"Name is longer than {MAX_NAME_LENGTH} characters")
            if url:
                try:
                    website = parse_website(url)
                except InvalidWebsite as exc:
                    row.errors.append(str(exc))
                else:
                    row.website_url, row.canonical_domain = website.url, website.canonical_domain
                    row.name = row.name or website.canonical_domain
            elif not name:
                row.errors.append("Either a name or a website is required")
            if not row.errors:
                key = row.canonical_domain or f"name:{row.name.lower()}"
                if key in seen:
                    row.duplicate_of_line = seen[key]
                else:
                    seen[key] = line_no
            rows.append(row)
    except csv.Error as exc:
        raise CsvFormatError(f"File is not valid CSV: {exc}") from exc
    if not rows:
        raise CsvFormatError("No companies found in the file")
    return rows
