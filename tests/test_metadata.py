"""Tests for the generic CROPro case-level metadata loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from cropro.metadata import CaseMetadataEntry, load_case_metadata

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _csv(tmp_path, content: str, name: str = "meta.csv") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Basic loading
# --------------------------------------------------------------------------- #


def test_positive_and_negative_from_csv(tmp_path):
    csv = _csv(
        tmp_path,
        "patient_id,study_id,case_csPCa\n"
        "10000,1000000,NO\n"
        "10001,1000001,YES\n",
    )
    entries = load_case_metadata(
        csv_path=csv,
        case_id_columns=["patient_id", "study_id"],
        case_id_format="{patient_id}_{study_id}",
        positive_column="case_csPCa",
        positive_values=["YES"],
    )
    assert entries["10000_1000000"].is_positive is False
    assert entries["10001_1000001"].is_positive is True


def test_positive_comparison_is_case_insensitive(tmp_path):
    csv = _csv(tmp_path, "id,label\nA,yes\nB,no\nC,YES\nD,Yes\n")
    entries = load_case_metadata(
        csv_path=csv,
        case_id_columns=["id"],
        case_id_format="{id}",
        positive_column="label",
        positive_values=["YES"],
    )
    assert entries["A"].is_positive is True
    assert entries["B"].is_positive is False
    assert entries["C"].is_positive is True
    assert entries["D"].is_positive is True


def test_missing_csv_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Metadata CSV not found"):
        load_case_metadata(
            csv_path=tmp_path / "missing.csv",
            case_id_columns=["id"],
            case_id_format="{id}",
            positive_column="label",
            positive_values=["1"],
        )


# --------------------------------------------------------------------------- #
# Raw values & manifest_columns
# --------------------------------------------------------------------------- #


def test_raw_values_include_all_columns_by_default(tmp_path):
    csv = _csv(
        tmp_path,
        "patient_id,study_id,case_ISUP,case_csPCa\n"
        "10001,1000001,2,YES\n",
    )
    entries = load_case_metadata(
        csv_path=csv,
        case_id_columns=["patient_id", "study_id"],
        case_id_format="{patient_id}_{study_id}",
        positive_column="case_csPCa",
        positive_values=["YES"],
    )
    raw = entries["10001_1000001"].raw
    assert raw["case_ISUP"] == "2"
    assert raw["case_csPCa"] == "YES"
    assert raw["patient_id"] == "10001"


def test_manifest_columns_limits_raw_output(tmp_path):
    csv = _csv(
        tmp_path,
        "patient_id,study_id,case_ISUP,case_csPCa,center\n"
        "10001,1000001,2,YES,RUMC\n",
    )
    entries = load_case_metadata(
        csv_path=csv,
        case_id_columns=["patient_id", "study_id"],
        case_id_format="{patient_id}_{study_id}",
        positive_column="case_csPCa",
        positive_values=["YES"],
        manifest_columns=["case_csPCa", "case_ISUP"],
    )
    raw = entries["10001_1000001"].raw
    assert set(raw.keys()) == {"case_csPCa", "case_ISUP"}
    assert "center" not in raw
    assert "patient_id" not in raw


# --------------------------------------------------------------------------- #
# Multi-value positive_values
# --------------------------------------------------------------------------- #


def test_multiple_positive_values(tmp_path):
    csv = _csv(tmp_path, "id,status\nA,positive\nB,1\nC,negative\n")
    entries = load_case_metadata(
        csv_path=csv,
        case_id_columns=["id"],
        case_id_format="{id}",
        positive_column="status",
        positive_values=["positive", "1"],
    )
    assert entries["A"].is_positive is True
    assert entries["B"].is_positive is True
    assert entries["C"].is_positive is False


# --------------------------------------------------------------------------- #
# Schema integration
# --------------------------------------------------------------------------- #


def test_schema_to_metadata_config_returns_none_without_section(tmp_path):
    from cropro.schema import DatasetSchema

    schema_path = tmp_path / "s.toml"
    schema_path.write_text("[dataset]\nname='X'\n", encoding="utf-8")
    schema = DatasetSchema.load(schema_path)
    assert schema.to_metadata_config() is None


def test_schema_to_metadata_config_returns_kwargs(tmp_path):
    from cropro.schema import DatasetSchema

    schema_path = tmp_path / "s.toml"
    schema_path.write_text(
        '[metadata]\n'
        'csv_path = "data/meta.csv"\n'
        'case_id_columns = ["patient_id", "study_id"]\n'
        'case_id_format = "{patient_id}_{study_id}"\n'
        'positive_column = "case_csPCa"\n'
        'positive_values = ["YES"]\n'
        'manifest_columns = ["case_csPCa", "case_ISUP"]\n',
        encoding="utf-8",
    )
    schema = DatasetSchema.load(schema_path)
    cfg = schema.to_metadata_config()
    assert cfg is not None
    assert cfg["csv_path"] == "data/meta.csv"
    assert cfg["positive_column"] == "case_csPCa"
    assert cfg["positive_values"] == ["YES"]
    assert cfg["manifest_columns"] == ["case_csPCa", "case_ISUP"]


def test_metadata_exported_from_package():
    from cropro import CaseMetadataEntry as pub_entry
    from cropro import load_case_metadata as pub_loader

    assert pub_entry is CaseMetadataEntry
    assert pub_loader is load_case_metadata


