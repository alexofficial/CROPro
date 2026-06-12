"""Generic case-level metadata loader for CROPro.

A metadata file maps case identifiers to clinical / label information.
Configure through the ``[metadata]`` section of a dataset schema TOML::

    [metadata]
    # Path to the CSV or TSV containing case-level information.
    csv_path        = "dataset/MyDataset/labels/clinical_information.csv"
    # CSV columns whose values together build the case stem (case identifier).
    case_id_columns = ["patient_id", "study_id"]
    # Python format string that combines the id columns into the case stem.
    case_id_format  = "{patient_id}_{study_id}"
    # Column whose value is used to classify a case as positive or negative.
    positive_column = "case_csPCa"
    # Values in *positive_column* that mean positive (case-insensitive).
    positive_values = ["YES"]
    # Optional: subset of CSV columns to embed in the split manifest per case.
    # Leave empty to omit all raw metadata from the manifest.
    manifest_columns = ["case_csPCa", "case_ISUP"]

All keys except ``csv_path`` and ``positive_column`` have sensible defaults.
This design is dataset-agnostic: point ``csv_path`` at any tabular file with a
case-identifier column and a positivity column to plug in a new dataset.

Typical usage::

    from cropro.metadata import load_case_metadata

    entries = load_case_metadata(
        csv_path="dataset/MyDataset/labels/clinical_information.csv",
        case_id_columns=["patient_id", "study_id"],
        case_id_format="{patient_id}_{study_id}",
        positive_column="case_csPCa",
        positive_values=["YES"],
    )
    # entries["10001_1000001"].is_positive  -> True/False
    # entries["10001_1000001"].raw          -> {"patient_id": "10001", "case_csPCa": "YES", ...}
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaseMetadataEntry:
    """Metadata record for a single case.

    Attributes
    ----------
    case_id:
        Case stem (e.g. ``"10001_1000001"``).
    is_positive:
        Derived positivity flag from the configured column + allowed values.
    raw:
        Full row from the CSV, keyed by column name. Values are stripped strings.
    """

    case_id: str
    is_positive: bool
    raw: dict[str, str] = field(default_factory=dict)


def load_case_metadata(
    csv_path: str | Path,
    *,
    case_id_columns: list[str] | None = None,
    case_id_format: str = "{patient_id}_{study_id}",
    positive_column: str,
    positive_values: list[str] | None = None,
    manifest_columns: list[str] | None = None,
) -> dict[str, CaseMetadataEntry]:
    """Load case-level metadata from a CSV file.

    Parameters
    ----------
    csv_path:
        Path to a CSV (or TSV) file with a header row.
    case_id_columns:
        CSV columns whose values are substituted into *case_id_format* to
        produce each case stem.  Defaults to ``["patient_id", "study_id"]``.
    case_id_format:
        Python format string with ``{column_name}`` placeholders.
        Default: ``"{patient_id}_{study_id}"``.
    positive_column:
        CSV column whose value determines whether a case is positive.
    positive_values:
        Values in *positive_column* considered positive.
        Comparison is **case-insensitive**. Defaults to ``["YES"]``.
    manifest_columns:
        Optional subset of CSV columns to expose in the ``raw`` output.
        When ``None`` (default) **all** columns are kept in ``raw``.

    Returns
    -------
    dict[str, CaseMetadataEntry]
        Keyed by case stem.  Rows where the id-column values are empty or
        the format string fails are silently skipped.

    Raises
    ------
    FileNotFoundError
        When *csv_path* does not exist.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Metadata CSV not found: {path}")

    if case_id_columns is None:
        case_id_columns = ["patient_id", "study_id"]
    if positive_values is None:
        positive_values = ["YES"]

    positive_set = {str(v).strip().lower() for v in positive_values}
    entries: dict[str, CaseMetadataEntry] = {}

    dialect = "excel"
    if str(path).endswith((".tsv", ".tab")):
        dialect = "excel-tab"

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, dialect=dialect)
        for row in reader:
            # Strip all values so leading/trailing whitespace never bites.
            stripped = {k: (v or "").strip() for k, v in row.items()}

            # Build the case stem from the configured columns.
            try:
                case_id = case_id_format.format(**{col: stripped[col] for col in case_id_columns})
            except KeyError:
                continue  # row is missing a required id column
            if not case_id:
                continue

            raw_val = stripped.get(positive_column, "").lower()
            is_positive = raw_val in positive_set

            # Optionally limit which columns are exposed in raw.
            if manifest_columns:
                raw = {col: stripped.get(col, "") for col in manifest_columns}
            else:
                raw = stripped

            entries[case_id] = CaseMetadataEntry(
                case_id=case_id,
                is_positive=is_positive,
                raw=raw,
            )

    return entries
