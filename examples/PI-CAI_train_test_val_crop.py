"""Crop the resampled PI-CAI dataset and split into Train / Validation / Test.

Run the resample pipeline first so every case has its aligned T2W / ADC / HBV
and the gland/lesion masks side by side::

    uv run cropro resample --config config/resample_paths.ini

-----------------------------------------------------------------------
Cropping strategy
-----------------------------------------------------------------------

TRAIN
    Uses ``random`` (or any configured ``train_crop_method``).  Random
    sampling gives data augmentation and sees many different prostate
    sub-regions per slice.

VALIDATION / TEST
    Always uses ``stride``.  Stride guarantees that the entire prostate
    area is covered on every slice without gaps, which is required for
    **patient-level inference**: the per-crop model predictions are later
    aggregated (e.g. max-pool) back into a single patient score.

-----------------------------------------------------------------------
Annotation quality filter  (``human_annotations_only_in_test``)
-----------------------------------------------------------------------

When ``human_annotations_only_in_test = True`` (default), **positive cases
in the test set are restricted to those with human expert lesion
delineations**.  AI-annotated positives are moved to train / val only.

For PI-CAI, human expert delineations live under::

    dataset/PI-CAI/picai_labels/csPCa_lesion_delineations/Human_expert/

The script auto-detects which case stems have a file there.  Negative
cases are always eligible for the test set (they have no lesion annotation
to worry about).

To apply the same logic to another dataset, set
``human_annotations_only_in_test = False`` (all cases eligible for test)
or supply a custom ``human_annotated_stems`` set.

-----------------------------------------------------------------------
Split level  (``split_level`` variable below)
-----------------------------------------------------------------------

``"patient"``  (default, recommended for test/val)
    Every slice that contains the prostate gland mask is cropped — not
    just the ones that contain a lesion.  This is required for
    patient-level evaluation because the model must score the *entire*
    prostate volume and the per-crop predictions are aggregated back into
    one score per patient.  Maps to ``keep_all_slice=True``.

``"lesion"``
    Only the slices that contain lesion annotations (for positive cases)
    or the central gland slices (for negative cases) are included.  Use
    this when training at the slice / image level and you want each
    training sample to be close to the lesion.  Maps to
    ``keep_all_slice=False``.

-----------------------------------------------------------------------
Dataset splitting
-----------------------------------------------------------------------

Splitting is done at the **patient** level so that all crops from the
same patient end up in the same subset.  With ``stratify=True`` (default)
positive and negative cases are split independently, preserving the
positive fraction in each subset.

Outputs are written to::

    dataset/cropro/PI-CAI/<run_name>/train/  <patient>/<stem>/
    dataset/cropro/PI-CAI/<run_name>/val/    <patient>/<stem>/
    dataset/cropro/PI-CAI/<run_name>/test/   <patient>/<stem>/
"""

import pathlib

import SimpleITK as sitk

from cropro import CropConfig, CROPro, DatasetSplit, SplitConfig, split_cases

current_path = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# CROPRO settings — shared across all splits
# ---------------------------------------------------------------------------
sequence_type = "bpMRI"
pixel_spacing = 0.4
crop_image_size = 128
crop_stride = 32
sample_number = 12
c_min_positive = 0.2
do_normalization = True
normalized_image = not do_normalization
skip_existing_slices = True
number_of_slices_to_exclude_from_mask_gland = 1
saved_image_type = "png"
t2w_normalization_method = "gaussian"

# Crop method used for training (any of "center", "random", "stride").
train_crop_method = "random"
# Validation and test ALWAYS use "stride" for full patient-level coverage.
eval_crop_method = "stride"

# ---------------------------------------------------------------------------
# Annotation quality filter
# ---------------------------------------------------------------------------
# When True, positive cases in the TEST set are restricted to those with
# human expert lesion delineations.  AI-annotated positives go to train/val
# only.  Negative cases are always eligible for test.
#
# For PI-CAI, set the path to the Human_expert delineation folder below.
# For other datasets: set to False, or build your own human_annotated_stems
# set and pass it to split_cases().
#
human_annotations_only_in_test = True  # True | False
picai_human_expert_dir = (
    current_path / "dataset" / "PI-CAI" / "picai_labels"
    / "csPCa_lesion_delineations" / "Human_expert"
)

# ---------------------------------------------------------------------------
# Split level
# ---------------------------------------------------------------------------
# Controls which SLICES are included when generating crops:
#
#   "patient"  — include ALL prostate gland slices (recommended for val/test).
#               Patient-level inference requires the full prostate volume so
#               that per-crop predictions can be aggregated per patient.
#               Sets keep_all_slice=True.
#
#   "lesion"   — include only lesion-containing slices for positive cases and
#               central gland slices for negative cases.  Useful when training
#               at image/slice level where lesion context is important.
#               Sets keep_all_slice=False.
#
split_level = "patient"  # "patient" | "lesion"

# ---------------------------------------------------------------------------
# Dataset split configuration
# ---------------------------------------------------------------------------
split_config = SplitConfig(
    train_ratio=0.70,
    val_ratio=0.15,
    test_ratio=0.15,
    seed=42,
    stratify=True,  # preserve positive/negative ratio in each split
    split_level=split_level,
)

# A unique name for this cropping run (encodes key settings).
run_name = (
    f"PICAI_train{train_crop_method}_eval{eval_crop_method}"
    f"_{pixel_spacing}_{crop_image_size}"
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
images_root = current_path / "dataset" / "PI-CAI" / "images_resampled"
output_root = current_path / "dataset" / "cropro" / "PI-CAI" / run_name


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def discover_cases(root: pathlib.Path) -> list[tuple[str, str]]:
    """Return sorted ``(patient_id, case_stem)`` pairs for every resampled T2W."""
    cases: list[tuple[str, str]] = []
    for patient_dir in sorted(root.iterdir()):
        if not patient_dir.is_dir():
            continue
        for t2w_file in patient_dir.glob("*_t2w.mha"):
            stem = t2w_file.name[: -len("_t2w.mha")]
            cases.append((patient_dir.name, stem))
    return sorted(cases)


def human_annotated_cases(
    all_cases: list[tuple[str, str]],
    human_expert_dir: pathlib.Path,
) -> set[tuple[str, str]]:
    """Return the subset of *all_cases* that have a human expert annotation.

    Works by checking whether any file whose name starts with the case stem
    exists under *human_expert_dir*.  The folder layout is expected to be
    flat or one level deep (e.g. ``Human_expert/<stem>.nii.gz`` or
    ``Human_expert/<patient>/<stem>.nii.gz``).

    For a different dataset, replace this function with one that reads your
    own annotation-quality metadata (e.g. a CSV column, a JSON manifest, etc.).
    """
    if not human_expert_dir.is_dir():
        return set()
    # Build a lookup of all stems that have at least one file in the dir tree.
    annotated_stems: set[str] = set()
    for f in human_expert_dir.rglob("*"):
        if f.is_file():
            # Strip known medical-image suffixes to get the bare stem.
            name = f.name
            for suffix in (".nii.gz", ".mha", ".nrrd", ".nii"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            else:
                name = f.stem
            annotated_stems.add(name)
    return {(pid, stem) for pid, stem in all_cases if stem in annotated_stems}


def smallest_lesion_label(mask_path: pathlib.Path) -> int | None:
    """Return the smallest non-zero label in a lesion mask, or ``None`` if empty."""
    array = sitk.GetArrayFromImage(sitk.ReadImage(str(mask_path)))
    labels = array[array > 0]
    return int(labels.min()) if labels.size else None


def crop_case(
    patient_id: str,
    stem: str,
    *,
    subset: str,
    crop_method: str,
) -> None:
    """Crop a single case and write crops into ``output_root/<subset>/``."""
    case_dir = images_root / patient_id
    orig_img_path_t2w = case_dir / f"{stem}_t2w.mha"
    orig_img_path_adc = case_dir / f"{stem}_adc.mha"
    orig_img_path_hbv = case_dir / f"{stem}_hbv.mha"
    seg_img_path_gland = case_dir / f"{stem}_gland.nii.gz"
    seg_img_path_lesion = case_dir / f"{stem}_lesion.nii.gz"

    required = [orig_img_path_t2w, orig_img_path_adc, orig_img_path_hbv, seg_img_path_gland]
    if not all(p.exists() for p in required):
        print(f"[SKIP] {stem}: missing one or more required files")
        return

    # Lesion file is only written for positive cases; auto-detect the label
    # threshold so Bosma22a masks labelled 1, 2, 3, … are not dropped.
    tumor_label_level = (
        smallest_lesion_label(seg_img_path_lesion)
        if seg_img_path_lesion.exists()
        else None
    )
    is_positive = tumor_label_level is not None
    patient_status = "positive" if is_positive else "negative"

    path_to_save = output_root / subset / patient_id / stem

    config = CropConfig(
        crop_method=crop_method,
        orig_img_path_t2w=orig_img_path_t2w,
        orig_img_path_adc=orig_img_path_adc,
        orig_img_path_hbv=orig_img_path_hbv,
        seg_img_path=seg_img_path_gland,
        seg_img_path_lesion=seg_img_path_lesion if is_positive else None,
        patient_status=patient_status,
        sequence_type=sequence_type,
        tumor_label_level=tumor_label_level if is_positive else 2,
        pixel_spacing=pixel_spacing,
        crop_image_size=crop_image_size,
        crop_stride=crop_stride,
        sample_number=sample_number,
        normalized_image=normalized_image,
        do_normalization=do_normalization,
        saved_image_type=saved_image_type,
        path_to_save=path_to_save,
        c_min_positive=c_min_positive,
        keep_all_slice=split_config.keep_all_slice,
        skip_existing_slices=skip_existing_slices,
        number_of_slices_to_exclude_from_mask_gland=number_of_slices_to_exclude_from_mask_gland,
        t2w_normalization_method=t2w_normalization_method,
    )
    print(f"[{subset.upper():5s}] {patient_status:8s} {crop_method:6s}  {stem}")
    CROPro(config).run()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # 1. Discover all cases.
    all_cases = discover_cases(images_root)
    if not all_cases:
        raise FileNotFoundError(
            f"No resampled T2W files found under {images_root}.\n"
            "Run:  uv run cropro resample --config config/resample_paths.ini"
        )

    # 2. Identify positive cases (lesion file present and non-empty).
    positives: set[tuple[str, str]] = set()
    for patient_id, stem in all_cases:
        lesion_path = images_root / patient_id / f"{stem}_lesion.nii.gz"
        if lesion_path.exists() and smallest_lesion_label(lesion_path) is not None:
            positives.add((patient_id, stem))

    # 3. Build test_eligible: negatives are always eligible; for positives,
    #    restrict to human-annotated cases when the flag is set.
    negatives = set(all_cases) - positives
    if human_annotations_only_in_test:
        human_pos = human_annotated_cases(all_cases, picai_human_expert_dir)
        test_eligible: set[tuple[str, str]] | None = human_pos | negatives
        print(
            f"  annotation filter: {len(human_pos)} human-annotated positives eligible for test"
            f" (of {len(positives)} total positives)"
        )
    else:
        test_eligible = None  # all cases eligible

    # 4. Split at the patient level.
    split: DatasetSplit = split_cases(
        all_cases,
        positives=positives,
        test_eligible=test_eligible,
        config=split_config,
    )
    print(split.summary())
    print(
        f"  positives — train: {sum(1 for c in split.train if c in positives)}, "
        f"val: {sum(1 for c in split.val if c in positives)}, "
        f"test: {sum(1 for c in split.test if c in positives)}"
    )

    # 4. Crop — train uses configurable method; val/test use stride.
    subsets: list[tuple[str, list[tuple[str, str]], str]] = [
        ("train", split.train, train_crop_method),
        ("val",   split.val,   eval_crop_method),
        ("test",  split.test,  eval_crop_method),
    ]
    for subset_name, cases, method in subsets:
        print(f"\n{'='*60}")
        print(f"  Subset: {subset_name.upper()}  ({len(cases)} cases, crop_method={method})")
        print(f"{'='*60}")
        for patient_id, stem in cases:
            crop_case(patient_id, stem, subset=subset_name, crop_method=method)

    print("\nDone.  Crops written to:", output_root)


if __name__ == "__main__":
    main()
