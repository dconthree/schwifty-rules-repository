#!/usr/bin/env python3
"""Export the Schwifty Rules Repository schema 4 from Airtable."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_ID = "appcEYlv0o5RPwNS1"
SCHEMA_VERSION = 4
MAX_RULE_SELECTORS = 5
OUTPUT_PATH = Path("site/rules.json")

TABLES = {
    "instrument_groups": {
        "id": "tblEOyUiALZUuzUA6",
        "fields": {
            "name": "fldmyEdmJ7Af3dB9s",
            "domain_id": "fldZmLdAdgFxZQ3VC",
        },
    },
    "instruments": {
        "id": "tblVGZIJjx734XtY6",
        "fields": {
            "name": "fldDq51NsTIoDBaxs",
            "aliases": "fldCA8dMDNot5UxwZ",
            "instrument_group": "fldPPRTfKt1HLC71t",
            "domain_id": "fldgec11W2NGzeCjC",
        },
    },
    "articulations": {
        "id": "tblThb7UaMLCiNlkN",
        "fields": {
            "name": "fld2uUFVCyowan2vF",
            "domain_id": "fldDpRQZZAWgvLIeV",
            "aliases": "fldDFaDnMi1NTPfRa",
        },
    },
    "classifications": {
        "id": "tblxTtbxbXrqWrYc5",
        "fields": {
            "name": "fld9IgHYpwvshY3FY",
            "domain_id": "fldpySMMzQQMnqLst",
        },
    },
    "vocal_types": {
        "id": "tblO2HCkWjHmrYndv",
        "fields": {
            "name": "fldqRu8LaSLoMvsGo",
            "domain_id": "fldGH6dzkc6ISXatT",
        },
    },
    "taxonomy": {
        "id": "tbl3CQzX9cSrYKKfu",
        "fields": {
            "display_name": "fldqvvDLpSf1NqAIw",
            "instrument": "fldqf4xmweW2IAFkD",
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
            "classifications": "fldqA1uejbN4vesyA",
            "instruments": "fldxACRJ21P0H8rFx",
            "instrument_groups": "fldw31D3AzpjdAsei",
            "articulations": "fldvCxSHa9JAEEM2Y",
            "taxonomy_entries": "fldyYIfCIbCXSiZwa",
            "drums_fx_coupling": "fldca9CtGEAtqifAl",
            "domain_id": "fldeLPImY1cCEWzhb",
        },
    },
}


def fetch_records(token: str, table: dict[str, object]) -> list[dict[str, object]]:
    """Fetch every record and return field values keyed by Airtable field ID."""
    field_ids = list(table["fields"].values())
    records: list[dict[str, object]] = []
    offset: str | None = None

    while True:
        params: list[tuple[str, str]] = [
            ("pageSize", "100"),
            ("returnFieldsByFieldId", "true"),
            *(("fields[]", str(field_id)) for field_id in field_ids),
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
            raise RuntimeError(
                f"Airtable returned HTTP {error.code}: {details}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach Airtable: {error.reason}") from error

        records.extend(payload.get("records", []))
        offset = payload.get("offset")
        if not offset:
            return records


def fields(record: dict[str, object]) -> dict[str, object]:
    value = record.get("fields", {})
    if not isinstance(value, dict):
        raise ValueError(f"Invalid fields on Airtable record {record.get('id')}")
    return value


def required_text(record: dict[str, object], field_id: str, label: str) -> str:
    value = fields(record).get(field_id)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing on Airtable record {record['id']}")
    return value.strip()


def normalize_match_key(value: str) -> str:
    """Normalize canonical names and aliases for collision checks."""
    return " ".join(re.sub(r"[\W_]+", " ", value.casefold()).split())


def parse_aliases(
    record: dict[str, object], field_id: str, canonical_name: str, label: str
) -> list[str]:
    """Parse comma- or newline-separated aliases while preserving entered order."""
    value = fields(record).get(field_id)
    if value is None:
        return []
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text on Airtable record {record['id']}")

    canonical_key = normalize_match_key(canonical_name)
    aliases: list[str] = []
    seen: set[str] = set()
    for candidate in re.split(r"[,\r\n]+", value):
        alias = " ".join(candidate.split())
        if not alias:
            continue
        alias_key = normalize_match_key(alias)
        if not alias_key:
            raise ValueError(
                f"{label} contains an invalid alias on Airtable record {record['id']}"
            )
        if alias_key == canonical_key or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)

    return aliases


def links(record: dict[str, object], field_id: str) -> list[str]:
    value = fields(record).get(field_id, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Invalid linked-record value on Airtable record {record['id']}")
    return value


def one_link(
    record: dict[str, object], field_id: str, label: str, required: bool
) -> str | None:
    value = links(record, field_id)
    if len(value) > 1 or (required and len(value) != 1):
        expectation = "exactly one" if required else "zero or one"
        raise ValueError(
            f"{label} must contain {expectation} link on record {record['id']}"
        )
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


def resolve_one(record_id: str, index: dict[str, str], label: str) -> str:
    try:
        return index[record_id]
    except KeyError as error:
        raise ValueError(
            f"{label} references an unknown Airtable record: {record_id}"
        ) from error


def resolve_many(record_ids: list[str], index: dict[str, str], label: str) -> list[str]:
    return [resolve_one(record_id, index, label) for record_id in record_ids]


def name_by_airtable_id(
    indexed: list[tuple[dict[str, object], str]], field_id: str, label: str
) -> dict[str, str]:
    result: dict[str, str] = {}
    seen: dict[str, str] = {}

    for record, _ in indexed:
        name = required_text(record, field_id, label)
        normalized = name.casefold()
        if normalized in seen:
            raise ValueError(f"Duplicate {label}: {name!r} and {seen[normalized]!r}")
        seen[normalized] = name
        result[str(record["id"])] = name

    return result


def validate_unique_output_names(
    items: list[dict[str, object]], field: str, label: str
) -> None:
    seen: dict[str, str] = {}
    for item in items:
        value = item[field]
        if not isinstance(value, str):
            raise ValueError(f"Invalid {label} on {item['id']}")
        normalized = value.casefold()
        if normalized in seen:
            raise ValueError(f"Duplicate {label}: {value!r} and {seen[normalized]!r}")
        seen[normalized] = value


def validate_alias_ownership(items: list[dict[str, object]], label: str) -> None:
    canonical_owners: dict[str, tuple[str, str]] = {}
    for item in items:
        item_id = str(item["id"])
        item_name = str(item["name"])
        canonical_key = normalize_match_key(item_name)
        previous_owner = canonical_owners.get(canonical_key)
        if previous_owner and previous_owner[0] != item_id:
            raise ValueError(
                f"{label} names {previous_owner[1]!r} and {item_name!r} normalize "
                "to the same value"
            )
        canonical_owners[canonical_key] = (item_id, item_name)

    alias_owners: dict[str, tuple[str, str]] = {}
    for item in items:
        item_id = str(item["id"])
        item_name = str(item["name"])
        item_aliases = item.get("aliases")
        if not isinstance(item_aliases, list) or not all(
            isinstance(alias, str) for alias in item_aliases
        ):
            raise ValueError(f"Invalid aliases on {label} {item_name!r}")

        for alias in item_aliases:
            alias_key = normalize_match_key(alias)
            canonical_owner = canonical_owners.get(alias_key)
            if canonical_owner and canonical_owner[0] != item_id:
                raise ValueError(
                    f"{label} alias {alias!r} on {item_name!r} conflicts with "
                    f"canonical name {canonical_owner[1]!r}"
                )

            previous_owner = alias_owners.get(alias_key)
            if previous_owner and previous_owner[0] != item_id:
                raise ValueError(
                    f"{label} alias {alias!r} is assigned to both "
                    f"{previous_owner[1]!r} and {item_name!r}"
                )
            alias_owners[alias_key] = (item_id, item_name)


def build_document(
    raw: dict[str, list[dict[str, object]]], generated_at: str | None = None
) -> dict[str, object]:
    group_fields = TABLES["instrument_groups"]["fields"]
    group_index, indexed_groups = unique_index(
        raw["instrument_groups"],
        group_fields["domain_id"],
        "instrument_group_id",
        "ig_",
    )
    group_names = name_by_airtable_id(
        indexed_groups, group_fields["name"], "instrument_group_name"
    )
    instrument_groups = [
        {"id": domain_id, "name": group_names[str(record["id"])]}
        for record, domain_id in indexed_groups
    ]

    instrument_fields = TABLES["instruments"]["fields"]
    instrument_index, indexed_instruments = unique_index(
        raw["instruments"],
        instrument_fields["domain_id"],
        "instrument_id",
        "inst_",
    )
    instrument_names = name_by_airtable_id(
        indexed_instruments, instrument_fields["name"], "instrument_name"
    )
    instrument_group_by_airtable_id: dict[str, str] = {}
    instruments: list[dict[str, object]] = []
    for record, domain_id in indexed_instruments:
        airtable_id = str(record["id"])
        name = instrument_names[airtable_id]
        group_record_id = one_link(
            record,
            instrument_fields["instrument_group"],
            "instrument_group",
            True,
        )
        if group_record_id is None:  # one_link already enforces this; narrows the type.
            raise ValueError(f"Instrument {domain_id} has no instrument group")
        instrument_group_id = resolve_one(
            group_record_id, group_index, f"Instrument {domain_id}"
        )
        instrument_group_by_airtable_id[airtable_id] = instrument_group_id
        instruments.append(
            {
                "id": domain_id,
                "name": name,
                "aliases": parse_aliases(
                    record,
                    instrument_fields["aliases"],
                    name,
                    "instrument_aliases",
                ),
                "instrument_group_id": instrument_group_id,
            }
        )
    validate_alias_ownership(instruments, "Instrument")

    articulation_fields = TABLES["articulations"]["fields"]
    articulation_index, indexed_articulations = unique_index(
        raw["articulations"],
        articulation_fields["domain_id"],
        "articulation_id",
        "art_",
    )
    articulation_names = name_by_airtable_id(
        indexed_articulations, articulation_fields["name"], "articulation_name"
    )
    articulations: list[dict[str, object]] = []
    for record, domain_id in indexed_articulations:
        name = articulation_names[str(record["id"])]
        articulations.append(
            {
                "id": domain_id,
                "name": name,
                "aliases": parse_aliases(
                    record,
                    articulation_fields["aliases"],
                    name,
                    "articulation_aliases",
                ),
            }
        )
    validate_alias_ownership(articulations, "Articulation")

    classification_fields = TABLES["classifications"]["fields"]
    classification_index, indexed_classifications = unique_index(
        raw["classifications"],
        classification_fields["domain_id"],
        "classification_id",
        "class_",
    )
    classification_names = name_by_airtable_id(
        indexed_classifications,
        classification_fields["name"],
        "classification_name",
    )
    classifications = [
        {"id": domain_id, "name": classification_names[str(record["id"])]}
        for record, domain_id in indexed_classifications
    ]

    vocal_type_fields = TABLES["vocal_types"]["fields"]
    vocal_type_index, indexed_vocal_types = unique_index(
        raw["vocal_types"],
        vocal_type_fields["domain_id"],
        "vocal_type_id",
        "lyr_",
    )
    vocal_type_names = name_by_airtable_id(
        indexed_vocal_types, vocal_type_fields["name"], "vocal_type_name"
    )
    vocal_types = [
        {"id": domain_id, "name": vocal_type_names[str(record["id"])]}
        for record, domain_id in indexed_vocal_types
    ]

    taxonomy_fields = TABLES["taxonomy"]["fields"]
    taxonomy_index, indexed_taxonomy = unique_index(
        raw["taxonomy"],
        taxonomy_fields["domain_id"],
        "taxonomy_entry_id",
        "tax_",
    )
    taxonomy_entries: list[dict[str, object]] = []
    for record, domain_id in indexed_taxonomy:
        instrument_record_id = one_link(
            record, taxonomy_fields["instrument"], "instrument_name", True
        )
        articulation_record_id = one_link(
            record, taxonomy_fields["articulation"], "articulation_name", False
        )
        classification_record_id = one_link(
            record, taxonomy_fields["classification"], "classification", True
        )
        vocal_type_record_id = one_link(
            record, taxonomy_fields["vocal_type"], "vocal_type", True
        )
        if (
            instrument_record_id is None
            or classification_record_id is None
            or vocal_type_record_id is None
        ):
            raise ValueError(f"Taxonomy entry {domain_id} is incomplete")

        instrument_id = resolve_one(
            instrument_record_id, instrument_index, f"Taxonomy entry {domain_id}"
        )
        instrument_group_id = instrument_group_by_airtable_id[instrument_record_id]
        articulation_id = (
            resolve_one(
                articulation_record_id,
                articulation_index,
                f"Taxonomy entry {domain_id}",
            )
            if articulation_record_id
            else None
        )
        display_name = required_text(
            record, taxonomy_fields["display_name"], "display_name"
        )
        expected_display_name = instrument_names[instrument_record_id]
        if articulation_record_id:
            expected_display_name += f" {articulation_names[articulation_record_id]}"
        if display_name != expected_display_name:
            raise ValueError(
                f"Taxonomy entry {domain_id} display_name is {display_name!r}; "
                f"expected {expected_display_name!r}"
            )

        taxonomy_entries.append(
            {
                "id": domain_id,
                "display_name": display_name,
                "instrument_id": instrument_id,
                "instrument_group_id": instrument_group_id,
                "articulation_id": articulation_id,
                "classification_id": classification_index[classification_record_id],
                "classification": classification_names[classification_record_id],
                "vocal_type_id": vocal_type_index[vocal_type_record_id],
                "vocal_type": vocal_type_names[vocal_type_record_id],
            }
        )

    rule_fields = TABLES["rules"]["fields"]
    _, indexed_rules = unique_index(
        raw["rules"], rule_fields["domain_id"], "creative_rule_id", "rule_"
    )
    creative_mix_rules: list[dict[str, object]] = []
    for record, domain_id in indexed_rules:
        classification_ids = resolve_many(
            links(record, rule_fields["classifications"]),
            classification_index,
            f"Creative rule {domain_id}",
        )
        instrument_group_ids = resolve_many(
            links(record, rule_fields["instrument_groups"]),
            group_index,
            f"Creative rule {domain_id}",
        )
        instrument_ids = resolve_many(
            links(record, rule_fields["instruments"]),
            instrument_index,
            f"Creative rule {domain_id}",
        )
        articulation_ids = resolve_many(
            links(record, rule_fields["articulations"]),
            articulation_index,
            f"Creative rule {domain_id}",
        )
        taxonomy_entry_ids = resolve_many(
            links(record, rule_fields["taxonomy_entries"]),
            taxonomy_index,
            f"Creative rule {domain_id}",
        )
        selector_count = sum(
            len(values)
            for values in (
                classification_ids,
                instrument_group_ids,
                instrument_ids,
                articulation_ids,
                taxonomy_entry_ids,
            )
        )
        if not 1 <= selector_count <= MAX_RULE_SELECTORS:
            raise ValueError(
                f"Creative rule {domain_id} must contain between one and five "
                f"selectors; found {selector_count}"
            )

        mode = required_text(record, rule_fields["mode"], "mode")
        if mode not in {"IncludeOnly", "ExcludeOnly"}:
            raise ValueError(f"Creative rule {domain_id} has invalid mode: {mode!r}")

        coupling = fields(record).get(rule_fields["drums_fx_coupling"], False)
        if not isinstance(coupling, bool):
            raise ValueError(
                f"Creative rule {domain_id} has invalid drums_fx_coupling"
            )

        creative_mix_rules.append(
            {
                "id": domain_id,
                "name": required_text(
                    record, rule_fields["name"], "creative_rule_name"
                ),
                "mode": mode,
                "classification_ids": classification_ids,
                "instrument_group_ids": instrument_group_ids,
                "instrument_ids": instrument_ids,
                "articulation_ids": articulation_ids,
                "taxonomy_entry_ids": taxonomy_entry_ids,
                "drums_fx_coupling": coupling,
            }
        )

    validate_unique_output_names(taxonomy_entries, "display_name", "display_name")
    validate_unique_output_names(creative_mix_rules, "name", "creative_rule_name")

    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return {
        "generated_at": timestamp,
        "schema_version": SCHEMA_VERSION,
        "instrument_groups": sorted(instrument_groups, key=lambda item: item["id"]),
        "instruments": sorted(instruments, key=lambda item: item["id"]),
        "articulations": sorted(articulations, key=lambda item: item["id"]),
        "classifications": sorted(classifications, key=lambda item: item["id"]),
        "vocal_types": sorted(vocal_types, key=lambda item: item["id"]),
        "taxonomy_entries": sorted(taxonomy_entries, key=lambda item: item["id"]),
        "creative_mix_rules": sorted(
            creative_mix_rules, key=lambda item: item["id"]
        ),
    }


def main() -> int:
    token = os.environ.get("AIRTABLE_TOKEN")
    if not token:
        print("AIRTABLE_TOKEN is not configured", file=sys.stderr)
        return 1

    raw = {name: fetch_records(token, table) for name, table in TABLES.items()}
    document = build_document(raw)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_PATH.parent / ".nojekyll").touch()
    print(f"Exported schema {SCHEMA_VERSION} to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print(f"Export failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
