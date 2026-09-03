#!/usr/bin/env python3
"""Export the Schwifty Rules Repository from Airtable to site/rules.json."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_ID = "appcEYlv0o5RPwNS1"

TABLES = {
    "instrument_groups": {
        "id": "tblEOyUiALZUuzUA6",
        "fields": {
            "name": "fldmyEdmJ7Af3dB9s",
            "domain_id": "fldZmLdAdgFxZQ3VC",
        },
    },
    "articulations": {
        "id": "tblThb7UaMLCiNlkN",
        "fields": {
            "name": "fld2uUFVCyowan2vF",
            "domain_id": "fldDpRQZZAWgvLIeV",
        },
    },
    "taxonomy": {
        "id": "tbl3CQzX9cSrYKKfu",
        "fields": {
            "display_name": "fldqvvDLpSf1NqAIw",
            "instrument_group": "fldqf4xmweW2IAFkD",
            "articulation": "fld4WTO1pSEzjaqjB",
            "classification": "fldWjmBp4hCUKSvG1",
            "vocal_type": "fldbAmexGPiHWmlQB",
            "domain_id": "fldydkfFntIrASLA0",
        },
    },
    "rules": {
        "id": "tblog7myUR0VRsEge",
        "fields": {
            "name": "fld5a8dmTTtHQsKFb",
            "mode": "fldOTvdz3kU5WnLax",
            "instrument_groups": "fldw31D3AzpjdAsei",
            "articulations": "fldvCxSHa9JAEEM2Y",
            "taxonomy_entries": "fldyYIfCIbCXSiZwa",
            "drums_fx_coupling": "fldca9CtGEAtqifAl",
            "domain_id": "fldeLPImY1cCEWzhb",
        },
    },
}


def fetch_records(token: str, table: dict[str, object]) -> list[dict[str, object]]:
    field_ids = list(table["fields"].values())
    records: list[dict[str, object]] = []
    offset: str | None = None

    while True:
        params: list[tuple[str, str]] = [
            ("pageSize", "100"),
            ("returnFieldsByFieldId", "true"),
            *(("fields[]", field_id) for field_id in field_ids),
        ]
        if offset:
            params.append(("offset", offset))

        table_id = urllib.parse.quote(str(table["id"]), safe="")
        query = urllib.parse.urlencode(params)
        url = f"https://api.airtable.com/v0/{BASE_ID}/{table_id}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Airtable returned HTTP {error.code}: {details}") from error

        records.extend(payload.get("records", []))
        offset = payload.get("offset")
        if not offset:
            return records


def fields(record: dict[str, object]) -> dict[str, object]:
    return record.get("fields", {})


def required_text(record: dict[str, object], field_id: str, label: str) -> str:
    value = fields(record).get(field_id)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing on Airtable record {record['id']}")
    return value.strip()


def links(record: dict[str, object], field_id: str) -> list[str]:
    value = fields(record).get(field_id, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Invalid linked-record value on Airtable record {record['id']}")
    return value


def one_link(record: dict[str, object], field_id: str, label: str, required: bool) -> str | None:
    value = links(record, field_id)
    if len(value) > 1 or (required and len(value) != 1):
        expectation = "exactly one" if required else "zero or one"
        raise ValueError(f"{label} must contain {expectation} link on record {record['id']}")
    return value[0] if value else None


def unique_index(
    records: list[dict[str, object]], field_id: str, label: str, prefix: str
) -> tuple[dict[str, str], list[tuple[dict[str, object], str]]]:
    by_airtable_id: dict[str, str] = {}
    seen: set[str] = set()
    indexed: list[tuple[dict[str, object], str]] = []

    for record in records:
        domain_id = required_text(record, field_id, label)
        if not domain_id.startswith(prefix):
            raise ValueError(f"{label} {domain_id!r} must start with {prefix!r}")
        if domain_id in seen:
            raise ValueError(f"Duplicate {label}: {domain_id}")
        seen.add(domain_id)
        by_airtable_id[str(record["id"])] = domain_id
        indexed.append((record, domain_id))

    return by_airtable_id, indexed


def resolve_many(record_ids: list[str], index: dict[str, str], label: str) -> list[str]:
    try:
        return sorted(index[record_id] for record_id in record_ids)
    except KeyError as error:
        raise ValueError(f"{label} references an unknown Airtable record: {error.args[0]}") from error


def main() -> int:
    token = os.environ.get("AIRTABLE_TOKEN")
    if not token:
        print("AIRTABLE_TOKEN is not configured", file=sys.stderr)
        return 1

    raw = {name: fetch_records(token, table) for name, table in TABLES.items()}

    group_fields = TABLES["instrument_groups"]["fields"]
    group_index, indexed_groups = unique_index(
        raw["instrument_groups"], group_fields["domain_id"], "instrument_group_id", "ig_"
    )
    instrument_groups = [
        {
            "id": domain_id,
            "name": required_text(record, group_fields["name"], "instrument_group_name"),
        }
        for record, domain_id in indexed_groups
    ]

    articulation_fields = TABLES["articulations"]["fields"]
    articulation_index, indexed_articulations = unique_index(
        raw["articulations"], articulation_fields["domain_id"], "articulation_id", "art_"
    )
    articulations = [
        {
            "id": domain_id,
            "name": required_text(record, articulation_fields["name"], "articulation_name"),
        }
        for record, domain_id in indexed_articulations
    ]

    taxonomy_fields = TABLES["taxonomy"]["fields"]
    taxonomy_index, indexed_taxonomy = unique_index(
        raw["taxonomy"], taxonomy_fields["domain_id"], "taxonomy_entry_id", "tax_"
    )
    taxonomy_entries: list[dict[str, object]] = []
    for record, domain_id in indexed_taxonomy:
        group_record_id = one_link(
            record, taxonomy_fields["instrument_group"], "instrument_group_name", True
        )
        articulation_record_id = one_link(
            record, taxonomy_fields["articulation"], "articulation_name", False
        )
        taxonomy_entries.append(
            {
                "id": domain_id,
                "display_name": required_text(record, taxonomy_fields["display_name"], "display_name"),
                "instrument_group_id": group_index[group_record_id],
                "articulation_id": (
                    articulation_index[articulation_record_id] if articulation_record_id else None
                ),
                "classification": required_text(
                    record, taxonomy_fields["classification"], "classification"
                ),
                "vocal_type": required_text(record, taxonomy_fields["vocal_type"], "vocal_type"),
            }
        )

    rule_fields = TABLES["rules"]["fields"]
    _, indexed_rules = unique_index(
        raw["rules"], rule_fields["domain_id"], "creative_rule_id", "rule_"
    )
    creative_mix_rules: list[dict[str, object]] = []
    for record, domain_id in indexed_rules:
        group_ids = resolve_many(
            links(record, rule_fields["instrument_groups"]), group_index, "Rule"
        )
        articulation_ids = resolve_many(
            links(record, rule_fields["articulations"]), articulation_index, "Rule"
        )
        taxonomy_ids = resolve_many(
            links(record, rule_fields["taxonomy_entries"]), taxonomy_index, "Rule"
        )
        if not (group_ids or articulation_ids or taxonomy_ids):
            raise ValueError(f"Creative rule {domain_id} has no selectors")

        creative_mix_rules.append(
            {
                "id": domain_id,
                "name": required_text(record, rule_fields["name"], "creative_rule_name"),
                "mode": required_text(record, rule_fields["mode"], "mode"),
                "instrument_group_ids": group_ids,
                "articulation_ids": articulation_ids,
                "taxonomy_entry_ids": taxonomy_ids,
                "drums_fx_coupling": bool(
                    fields(record).get(rule_fields["drums_fx_coupling"], False)
                ),
            }
        )

    document = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "instrument_groups": sorted(instrument_groups, key=lambda item: item["id"]),
        "articulations": sorted(articulations, key=lambda item: item["id"]),
        "taxonomy_entries": sorted(taxonomy_entries, key=lambda item: item["id"]),
        "creative_mix_rules": sorted(creative_mix_rules, key=lambda item: item["id"]),
    }

    output = Path("site/rules.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output.parent / ".nojekyll").touch()
    print(f"Exported {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, RuntimeError, ValueError) as error:
        print(f"Export failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error