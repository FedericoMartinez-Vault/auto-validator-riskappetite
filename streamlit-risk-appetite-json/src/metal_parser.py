"""Parse and normalize Metal homeowners quote JSON exports."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from src.utils import is_blank

KEY_SUBMISSION_FIELDS = [
    "program",
    "state",
    "county",
    "city",
    "zip_code",
    "occupancy",
    "distance_to_coast",
    "coverage_a",
    "tiv",
    "construction_type",
    "year_built",
    "roof_year",
    "electrical_year",
    "plumbing_year",
    "hvac_year",
    "protection_class",
    "fire_protection",
    "aop_deductible",
    "hurricane_deductible",
    "wind_hail_deductible",
    "central_fire_alarm",
    "central_burglar_alarm",
    "residential_sprinkler",
    "water_leak_detection",
    "backup_generator",
    "prior_claims",
    "prior_claims_five",
    "prior_claims_over_2500",
    "prior_water_claims",
    "prior_non_water_claims",
    "premium_total",
    "net_premium",
    "gross_premium",
    "cat_modeling_hurricane_cat_score",
    "cat_modeling_aal",
    "cat_modeling_aal_to_premium",
    "collections_included",
]


def load_json(file: BytesIO | str) -> dict[str, Any]:
    """Load JSON from an uploaded file-like object or path."""
    if isinstance(file, (str, bytes)):
        with open(file, "rb") as handle:
            return json.load(handle)
    return json.load(file)


def get_field_value(fields: list[dict[str, Any]], field_name: str, default: Any = None) -> Any:
    """Return the Value for a field name from a Metal Fields list."""
    for field in fields:
        if field.get("Field") == field_name:
            value = field.get("Value")
            return default if is_blank(value) else value
    return default


def extract_objects(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return root Objects list."""
    objects = data.get("Objects", [])
    return objects if isinstance(objects, list) else []


def extract_fields_by_object(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Group object field lists by ObjectType and ObjectGroupIdentifier."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for obj in extract_objects(data):
        object_type = str(obj.get("ObjectType", "Unknown"))
        group_id = str(obj.get("ObjectGroupIdentifier", "default"))
        key = f"{object_type}::{group_id}"
        fields = obj.get("Fields", [])
        grouped[key] = fields if isinstance(fields, list) else []
    return grouped


def flatten_metal_json(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten all objects into a single field-name -> value map (last wins)."""
    flattened: dict[str, Any] = {}
    for fields in extract_fields_by_object(data).values():
        for field in fields:
            name = field.get("Field")
            if not name:
                continue
            value = field.get("Value")
            if not is_blank(value):
                flattened[name] = value
    return flattened


def _fields_for_type(data: dict[str, Any], object_type: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for obj in extract_objects(data):
        if obj.get("ObjectType") == object_type:
            obj_fields = obj.get("Fields", [])
            if isinstance(obj_fields, list):
                fields.extend(obj_fields)
    return fields


def _premium_value(data: dict[str, Any], key: str) -> Any:
    premium = data.get("Premium", {})
    if not isinstance(premium, dict):
        return None
    value = premium.get(key)
    return None if is_blank(value) else value


def _extract_forms(data: dict[str, Any]) -> list[dict[str, Any]]:
    forms = data.get("Forms", [])
    if not isinstance(forms, list):
        return []
    normalized: list[dict[str, Any]] = []
    for form in forms:
        if not isinstance(form, dict):
            continue
        normalized.append(
            {
                "Number": form.get("Number") or form.get("FormNumber"),
                "Description": form.get("Description"),
                "FormType": form.get("FormType"),
                "DocumentType": form.get("DocumentType"),
            }
        )
    return normalized


def _extract_collection_classes(data: dict[str, Any]) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    for obj in extract_objects(data):
        if obj.get("ObjectType") != "CollectionClass":
            continue
        fields = obj.get("Fields", [])
        if not isinstance(fields, list):
            continue
        entry: dict[str, Any] = {}
        for field in fields:
            name = field.get("Field")
            if not name:
                continue
            value = field.get("Value")
            if not is_blank(value):
                entry[name] = value
        if entry:
            classes.append(entry)
    return classes


def get_non_null_fields_by_group(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return non-null fields grouped by object type/group."""
    grouped: dict[str, dict[str, Any]] = {}
    for key, fields in extract_fields_by_object(data).items():
        non_null: dict[str, Any] = {}
        for field in fields:
            name = field.get("Field")
            value = field.get("Value")
            if name and not is_blank(value):
                non_null[name] = value
        if non_null:
            grouped[key] = non_null
    return grouped


def build_submission_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Build normalized submission summary for UI and agent prompt."""
    homeowner_fields = _fields_for_type(data, "Homeowner")
    collection_fields = _fields_for_type(data, "Collection")
    flattened = flatten_metal_json(data)
    all_non_null = get_non_null_fields_by_group(data)
    forms = _extract_forms(data)
    collection_classes = _extract_collection_classes(data)

    def hv(field_name: str, default: Any = None) -> Any:
        return get_field_value(homeowner_fields, field_name, default)

    submission = {
        "program": hv("Program"),
        "state": hv("RiskAddressState"),
        "county": hv("RiskAddressCounty"),
        "city": hv("RiskAddressCity"),
        "zip_code": hv("RiskAddressZipCode"),
        "occupancy": hv("Occupancy"),
        "distance_to_coast": hv("DistanceToCoast"),
        "coverage_a": hv("CoverageA"),
        "tiv": hv("ReinsuranceTotalTIV"),
        "construction_type": hv("ConstructionType"),
        "year_built": hv("YearBuilt"),
        "roof_year": hv("YearRoofUpdated"),
        "electrical_year": hv("YearElectricalUpdated"),
        "plumbing_year": hv("YearPlumbingUpdated"),
        "hvac_year": hv("YearHvacUpdated"),
        "protection_class": hv("ProtectionClass"),
        "fire_protection": hv("FireProtection"),
        "aop_deductible": hv("AopDeductible"),
        "hurricane_deductible": hv("HurricaneDeductible"),
        "wind_hail_deductible": hv("WindstormOrHailDeductible"),
        "central_fire_alarm": hv("CentralReportingFireAlarm"),
        "central_burglar_alarm": hv("CentralReportingBurglarAlarm"),
        "residential_sprinkler": hv("ResidentialSprinklerSystem"),
        "water_leak_detection": hv("WaterLeakDetectionSystem"),
        "backup_generator": hv("BackupGenerator"),
        "prior_claims": hv("PriorClaims"),
        "prior_claims_five": hv("PriorClaimsFive"),
        "prior_claims_over_2500": hv("PriorClaimsOver2500"),
        "prior_water_claims": hv("PriorWaterClaims"),
        "prior_non_water_claims": hv("PriorNonWaterClaims"),
        "premium_total": _premium_value(data, "TotalPremium"),
        "net_premium": _premium_value(data, "NetPremium"),
        "gross_premium": _premium_value(data, "GrossPremium"),
        "cat_modeling_hurricane_cat_score": hv("CATModeling_CATScore") or flattened.get("CATModeling_CATScore"),
        "cat_modeling_aal": hv("AAL") or flattened.get("AAL"),
        "cat_modeling_aal_to_premium": hv("CATModeling_AALToPremium") or flattened.get("CATModeling_AALToPremium"),
        "collections_included": get_field_value(collection_fields, "IncludeCoverage"),
    }

    missing_key_fields = [key for key in KEY_SUBMISSION_FIELDS if is_blank(submission.get(key))]

    object_count = len(extract_objects(data))
    field_count = sum(len(fields) for fields in extract_fields_by_object(data).values())
    non_null_count = sum(len(group) for group in all_non_null.values())

    return {
        "submission": submission,
        "all_non_null_fields_by_object": all_non_null,
        "missing_key_fields": missing_key_fields,
        "forms": forms,
        "collection_classes": collection_classes,
        "raw_counts": {
            "number_of_objects": object_count,
            "number_of_fields": field_count,
            "number_of_non_null_fields": non_null_count,
            "number_of_forms": len(forms),
        },
    }
