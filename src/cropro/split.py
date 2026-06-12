"""Patient/case-level train / validation / test splitting for CROPro.

Splitting is always done at the **patient** level (one unit = one patient)
so that all crops from the same patient end up in the same subset.  This
prevents data leakage between training, validation, and test sets.

``split_level`` (on :class:`SplitConfig`) controls which slices are
included when crops are generated for each subset:

* ``"patient"`` — all slices that contain the prostate gland mask are
  included.  This is required for patient-level inference, where the
  model must score the *entire* prostate volume and individual crop
  predictions are aggregated (e.g. max-pool) back into one patient
  score.  Maps to ``keep_all_slice=True`` in :class:`~cropro.CropConfig`.

* ``"lesion"`` — only the slices that contain the lesion (for positive
  cases) or the central gland slices (for negative cases) are included.
  Useful for image-level / slice-level training where you want the model
  to see lesion-rich context.  Maps to ``keep_all_slice=False`` in
  :class:`~cropro.CropConfig`, which trims
  ``number_of_slices_to_exclude_from_mask_gland`` edge slices from each
  end of the gland region; the per-crop lesion-overlap threshold then
  rejects any crop with insufficient lesion area.

**Annotation quality filtering** — :func:`split_cases` accepts an optional
``test_eligible`` set.  Only cases in that set can appear in the **test**
subset; all other cases are restricted to train / val.  This is dataset-
agnostic: pass human-annotated case identifiers as ``test_eligible`` to
guarantee that the test set is never evaluated against AI-generated labels.

For PI-CAI, human expert lesion delineations live under
``picai_labels/csPCa_lesion_delineations/Human_expert/``.  The example
``PI-CAI_train_test_val_crop.py`` auto-detects those case stems and passes
them (together with all negative cases) as ``test_eligible``.

Typical usage::

    from cropro import SplitConfig, DatasetSplit, split_cases

    cases = [("10000", "10000_1000000"), ("10001", "10001_1000001"), ...]
    positives = {("10001", "10001_1000001"), ...}
    # Restrict the test set to human-annotated positives + all negatives:
    human_annotated = {("10001", "10001_1000001"), ...}
    negatives = set(cases) - positives

    config = SplitConfig(train_ratio=0.70, val_ratio=0.15, test_ratio=0.15, seed=42)
    split = split_cases(
        cases,
        positives=positives,
        test_eligible=human_annotated | negatives,
        config=config,
    )
    print(split.summary())
    # -> DatasetSplit(train=..., val=..., test=..., total=...)

During **training** you may use any crop method (center / random / stride).
During **validation and testing** use *stride* so that the stride grid covers
the entire prostate area on every slice — this is required for patient-level
inference where individual crop predictions must be aggregated back into a
per-patient score.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from typing import Any, Literal

SplitLevel = Literal["patient", "lesion"]


@dataclass(slots=True)
class SplitConfig:
    """Configuration for deterministic dataset splitting.

    The three ratios must sum to exactly 1.0 (within floating-point tolerance).

    Parameters
    ----------
    train_ratio:
        Fraction of cases allocated to the training set (default 0.70).
    val_ratio:
        Fraction of cases allocated to the validation set (default 0.15).
    test_ratio:
        Fraction of cases allocated to the test set (default 0.15).
    seed:
        Random seed used for shuffling; guarantees reproducibility.
    stratify:
        When ``True`` (default) and *positives* is provided to
        :func:`split_cases`, positive and negative cases are split
        independently so each subset preserves the original positive
        fraction.
    split_level:
        Controls which slices are included when generating crops.

        ``"patient"`` — every slice that contains the prostate gland mask
        is cropped.  Use this when evaluation is at the **patient level**
        (e.g. aggregate per-crop scores into one patient score).  This
        mode should always be used for validation and test sets when
        stride cropping is selected, because full volumetric coverage is
        required for aggregation.  Maps to ``keep_all_slice=True``.

        ``"lesion"`` — only the lesion-containing slices (positive cases)
        or central gland slices (negative cases) are included.  Use this
        when training at the **slice / image level** and you want each
        sample to be close to the lesion.  Maps to ``keep_all_slice=False``.
    """

    train_ratio: float = 0.70
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    seed: int = 42
    stratify: bool = True
    split_level: SplitLevel = "patient"

    def __post_init__(self) -> None:
        total = self.train_ratio + self.val_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"train_ratio + val_ratio + test_ratio must sum to 1.0, got {total:.6f}."
            )
        for attr in ("train_ratio", "val_ratio", "test_ratio"):
            v = getattr(self, attr)
            if v < 0:
                raise ValueError(f"{attr} must be >= 0.")
        if self.split_level not in {"patient", "lesion"}:
            raise ValueError(
                f"split_level must be 'patient' or 'lesion', got {self.split_level!r}."
            )

    @property
    def keep_all_slice(self) -> bool:
        """Derived ``keep_all_slice`` value for :class:`~cropro.CropConfig`.

        ``True`` for ``"patient"`` level (all prostate slices),
        ``False`` for ``"lesion"`` level (edge slices excluded).
        """
        return self.split_level == "patient"


@dataclass
class DatasetSplit:
    """Result of splitting cases into train / val / test subsets.

    Each attribute holds the list of case identifiers assigned to that
    subset.  The identifiers have the same type as the elements passed to
    :func:`split_cases`.
    """

    train: list[Any] = field(default_factory=list)
    val: list[Any] = field(default_factory=list)
    test: list[Any] = field(default_factory=list)

    def summary(self) -> str:
        """One-line human-readable description of split sizes."""
        total = len(self.train) + len(self.val) + len(self.test)
        return (
            f"DatasetSplit(train={len(self.train)}, val={len(self.val)}, "
            f"test={len(self.test)}, total={total})"
        )


def split_cases(
    cases: list[Any],
    *,
    positives: set[Any] | None = None,
    test_eligible: set[Any] | None = None,
    config: SplitConfig | None = None,
) -> DatasetSplit:
    """Split *cases* into train / val / test subsets at the patient level.

    All crops that belong to a patient remain in the same subset so there is
    no data leakage.

    Parameters
    ----------
    cases:
        Ordered sequence of case identifiers (e.g. patient-id strings or
        ``(patient_id, stem)`` tuples).  Duplicate entries are silently
        deduplicated while preserving insertion order.
    positives:
        Optional set of cases that are positive (contain lesions).  When
        provided and ``config.stratify=True``, positive and negative cases
        are split independently to keep the positive fraction consistent
        across all three subsets.
    test_eligible:
        Optional set of cases that are **allowed** to appear in the test
        subset.  Cases absent from this set are restricted to train / val
        and will never be placed in test.  This is the recommended way to
        ensure that the test set is only evaluated against high-quality
        (e.g. human expert) annotations.

        For PI-CAI pass the union of all negative cases and the positive
        cases that have human expert lesion delineations::

            test_eligible = human_annotated_positives | negatives

        When ``None`` (default) every case is eligible for the test subset.
    config:
        Splitting parameters.  Defaults to ``SplitConfig()`` (70 / 15 / 15,
        seed=42, stratify=True).

    Returns
    -------
    DatasetSplit
        Named train / val / test lists of case identifiers.
    """
    if config is None:
        config = SplitConfig()

    rng = _random.Random(config.seed)

    # Deduplicate while preserving insertion order.
    seen: set[Any] = set()
    unique: list[Any] = []
    for c in cases:
        # Lists are not hashable; convert to tuple for the seen-set key.
        key = tuple(c) if isinstance(c, list) else c
        if key not in seen:
            seen.add(key)
            unique.append(c)

    if test_eligible is not None:
        eligible = [c for c in unique if c in test_eligible]
        ineligible = [c for c in unique if c not in test_eligible]
        return _merge(
            _split_eligible(eligible, config, rng, positives),
            _split_train_val_only(ineligible, config, rng, positives),
        )

    if config.stratify and positives is not None:
        pos = [c for c in unique if c in positives]
        neg = [c for c in unique if c not in positives]
        return _merge(
            _split_list(pos, config, rng),
            _split_list(neg, config, rng),
        )

    return _split_list(unique, config, rng)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_list(cases: list[Any], config: SplitConfig, rng: _random.Random) -> DatasetSplit:
    """Shuffle *cases* and cut at the configured ratios."""
    shuffled = cases.copy()
    rng.shuffle(shuffled)
    n = len(shuffled)
    n_train = round(n * config.train_ratio)
    n_val = round(n * config.val_ratio)
    # Test takes the remainder so the total is always exactly len(cases).
    return DatasetSplit(
        train=shuffled[:n_train],
        val=shuffled[n_train : n_train + n_val],
        test=shuffled[n_train + n_val :],
    )


def _split_eligible(
    cases: list[Any],
    config: SplitConfig,
    rng: _random.Random,
    positives: set[Any] | None,
) -> DatasetSplit:
    """Split *cases* that are eligible for all three subsets (train/val/test)."""
    if config.stratify and positives is not None:
        pos = [c for c in cases if c in positives]
        neg = [c for c in cases if c not in positives]
        return _merge(_split_list(pos, config, rng), _split_list(neg, config, rng))
    return _split_list(cases, config, rng)


def _split_train_val_only(
    cases: list[Any],
    config: SplitConfig,
    rng: _random.Random,
    positives: set[Any] | None,
) -> DatasetSplit:
    """Split *cases* that must NOT appear in the test subset (train/val only).

    The train/val ratio is preserved: each case is assigned to train or val
    with relative probability ``train_ratio : val_ratio``.
    """
    tv_total = config.train_ratio + config.val_ratio
    if tv_total == 0:
        return DatasetSplit()
    rel_train = config.train_ratio / tv_total

    def _tv_split(cs: list[Any]) -> DatasetSplit:
        shuffled = cs.copy()
        rng.shuffle(shuffled)
        n_train = round(len(shuffled) * rel_train)
        return DatasetSplit(train=shuffled[:n_train], val=shuffled[n_train:], test=[])

    if config.stratify and positives is not None:
        pos = [c for c in cases if c in positives]
        neg = [c for c in cases if c not in positives]
        return _merge(_tv_split(pos), _tv_split(neg))
    return _tv_split(cases)


def _merge(a: DatasetSplit, b: DatasetSplit) -> DatasetSplit:
    """Concatenate two :class:`DatasetSplit` objects subset-wise."""
    return DatasetSplit(
        train=a.train + b.train,
        val=a.val + b.val,
        test=a.test + b.test,
    )
