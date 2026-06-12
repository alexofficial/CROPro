"""Reusable visualization helpers for CROPro notebooks.

Two public classes are provided:

``ResampleViewer``
    Compare T2W, ADC and HBV images before and after resampling onto the T2W
    grid, plus an overlay panel to verify spatial alignment.  Mirrors what
    ``check_resample_to_t2w.ipynb`` does interactively.

``CropViewer``
    Given a single aligned case (T2W + optional ADC/HBV + gland/lesion masks),
    compute and overlay the crop boxes produced by one or more cropping
    strategies (center, stride, random) on the full slice and then display the
    resulting crops side-by-side for each modality.  Mirrors what
    ``resample_then_crop_example.ipynb`` does interactively.

Both classes are *pure Python / NumPy / Matplotlib* – they do NOT depend on the
CROPro internal crop pipeline.  SimpleITK is imported lazily only when the
class is actually instantiated so that ``import cropro`` stays light.
"""

from __future__ import annotations

import math
import random as rng
from collections.abc import Sequence
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STRATEGY_COLORS = {
    "center": "#00E5FF",   # cyan
    "stride": "#FFEA00",   # yellow
    "random": "#FF6D00",   # orange
}

_MODALITY_CMAPS = {
    "T2W": "gray",
    "ADC": "gray",
    "HBV": "gray",
}


def _norm(arr: np.ndarray, lo: float = 1.0, hi: float = 99.0) -> np.ndarray:
    """Percentile-window an array to [0, 1] for display."""
    arr = arr.astype(np.float32)
    a, b = float(np.percentile(arr, lo)), float(np.percentile(arr, hi))
    if b <= a:
        return np.zeros_like(arr)
    return np.clip((arr - a) / (b - a), 0.0, 1.0)


def _load_gray(path: Path) -> np.ndarray:
    """Load a saved PNG crop as a float array in [0, 1]."""
    img = plt.imread(str(path))
    gray = img[..., :3].mean(axis=-1) if img.ndim == 3 else img.astype(np.float32)
    return gray.astype(np.float32)


def _read_sitk_array(path: Path) -> np.ndarray:
    """Read an image file with SimpleITK and return its array (z, y, x)."""
    import SimpleITK as sitk  # noqa: PLC0415  (lazy import)

    return sitk.GetArrayFromImage(sitk.ReadImage(str(path)))


# ---------------------------------------------------------------------------
# Strategy box computation (pure NumPy – mirrors the crop classes)
# ---------------------------------------------------------------------------

def _center_boxes(
    gland_slice: np.ndarray,
    crop_size: int,
) -> list[tuple[int, int, int, int]]:
    """Return the single (x1, y1, x2, y2) center-crop box or empty list."""
    ys, xs = np.where(gland_slice > 0)
    if len(xs) == 0:
        return []
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min, y_max = int(ys.min()), int(ys.max())
    cx = (x_min + x_max) // 2
    cy = (y_min + y_max) // 2
    x1 = cx - crop_size // 2
    y1 = cy - crop_size // 2
    x2 = x1 + crop_size
    y2 = y1 + crop_size
    H, W = gland_slice.shape
    if x1 < 0 or y1 < 0 or x2 > W or y2 > H:
        return []
    return [(x1, y1, x2, y2)]


def _stride_boxes(
    gland_slice: np.ndarray,
    crop_size: int,
    stride: int,
) -> list[tuple[int, int, int, int]]:
    """Return all stride-crop boxes (x1, y1, x2, y2) for one slice."""
    ys, xs = np.where(gland_slice > 0)
    if len(xs) == 0:
        return []
    min_i, max_i = int(ys.min()), int(ys.max())
    min_j, max_j = int(xs.min()), int(xs.max())
    range_i = max_i - min_i + 1
    range_j = max_j - min_j + 1
    center_i = round(min_i + range_i / 2)
    center_j = round(min_j + range_j / 2)

    strides_per_size = crop_size / stride
    nr_strides_i = max(math.ceil(range_i / stride), strides_per_size)
    nr_strides_j = max(math.ceil(range_j / stride), strides_per_size)
    full_range_i = stride * nr_strides_i
    full_range_j = stride * nr_strides_j
    nr_stride_steps_i = int(nr_strides_i - strides_per_size + 1)
    nr_stride_steps_j = int(nr_strides_j - strides_per_size + 1)

    ox1 = int(center_i - full_range_i / 2)
    ox2 = int(center_i + full_range_i / 2)
    oy1 = int(center_j - full_range_j / 2)
    oy2 = int(center_j + full_range_j / 2)

    H, W = gland_slice.shape
    if ox1 < 0 or oy1 < 0 or ox2 > H or oy2 > W:
        return []

    boxes = []
    for si in range(1, nr_stride_steps_i + 1):
        for sj in range(1, nr_stride_steps_j + 1):
            rx1 = (si - 1) * stride
            ry1 = (sj - 1) * stride
            # map back to full-image coords: note stride stores row=x, col=y
            final_x1 = ox1 + rx1
            final_y1 = oy1 + ry1
            boxes.append((final_y1, final_x1, final_y1 + crop_size, final_x1 + crop_size))
    return boxes


def _random_boxes(
    gland_slice: np.ndarray,
    crop_size: int,
    sample_size: int,
    seed: int | None = None,
) -> list[tuple[int, int, int, int]]:
    """Return randomly-sampled crop boxes (x1, y1, x2, y2).

    Coordinate convention: x=col (horizontal), y=row (vertical), matching the
    negativeRandomC implementation.
    """
    rng_inst = rng.Random(seed)
    ys, xs = np.where(gland_slice > 0)
    if len(xs) == 0:
        return []
    H, W = gland_slice.shape
    coords = list(zip(xs.tolist(), ys.tolist(), strict=False))
    boxes = []
    for _ in range(sample_size):
        cx, cy = rng_inst.choice(coords)
        x1 = cx - crop_size // 2
        y1 = cy - crop_size // 2
        x2 = x1 + crop_size
        y2 = y1 + crop_size
        if x1 >= 0 and y1 >= 0 and x2 <= W and y2 <= H:
            boxes.append((x1, y1, x2, y2))
    return boxes


# ---------------------------------------------------------------------------
# Public class 1: ResampleViewer
# ---------------------------------------------------------------------------

class ResampleViewer:
    """Visualize ADC/HBV → T2W resampling for one or more cases.

    Parameters
    ----------
    cases : list of dicts, each with keys ``"id"`` and SimpleITK images
        ``"t2w"``, ``"adc"``, ``"hbv"``.  Alternatively, pass ``t2w_paths``
        and ``images_root`` and call :meth:`from_paths` to build the list
        automatically.
    norm_lo, norm_hi : float
        Percentile range used when normalizing slices for display (default
        1 – 99).
    overlay_alpha : float
        Transparency of the ADC overlay in the fourth panel (default 0.4).

    Examples
    --------
    >>> from cropro.visualization import ResampleViewer
    >>> viewer = ResampleViewer(results)            # results from check notebook
    >>> viewer.show()                               # one figure per case
    >>> fig = viewer.figure(case_idx=0)            # single figure
    """

    def __init__(
        self,
        cases: list[dict],
        *,
        norm_lo: float = 1.0,
        norm_hi: float = 99.0,
        overlay_alpha: float = 0.4,
    ) -> None:
        self.cases = cases
        self.norm_lo = norm_lo
        self.norm_hi = norm_hi
        self.overlay_alpha = overlay_alpha

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_paths(
        cls,
        t2w_paths: Sequence[Path],
        *,
        norm_lo: float = 1.0,
        norm_hi: float = 99.0,
        overlay_alpha: float = 0.4,
    ) -> ResampleViewer:
        """Build from a list of T2W paths; ADC/HBV are auto-discovered.

        The method resamples ADC and HBV onto the T2W grid in-memory using the
        same B-spline filter as ``cropro.resample.resample_to_reference``.
        """
        import SimpleITK as sitk  # noqa: PLC0415

        from cropro.resample import resample_to_reference  # noqa: PLC0415


        def _seq_path(t2w: Path, seq: str) -> Path:
            stem = t2w.name
            for suffix in ("_t2w.mha", "_t2w.nii.gz"):
                if stem.endswith(suffix):
                    return t2w.with_name(stem[: -len(suffix)] + f"_{seq}.mha")
            return t2w.with_name(stem.replace("t2w", seq))

        cases = []
        for t2w_path in t2w_paths:
            t2w_path = Path(t2w_path)
            case_id = t2w_path.name.split("_t2w")[0]
            t2w_img = sitk.ReadImage(str(t2w_path))
            aligned: dict = {"id": case_id, "t2w": t2w_img}
            for seq in ("adc", "hbv"):
                seq_path = _seq_path(t2w_path, seq)
                if seq_path.exists():
                    moving = sitk.ReadImage(str(seq_path))
                    aligned[seq] = resample_to_reference(moving, t2w_img, is_mask=False)
                else:
                    aligned[seq] = None
            cases.append(aligned)
        return cls(cases, norm_lo=norm_lo, norm_hi=norm_hi, overlay_alpha=overlay_alpha)

    # ------------------------------------------------------------------
    # Figure builders
    # ------------------------------------------------------------------

    def figure(self, case_idx: int = 0, slice_idx: int | None = None) -> plt.Figure:
        """Return a Matplotlib figure for the case at *case_idx*.

        Panels: T2W | ADC (resampled) | HBV (resampled) | T2W + ADC overlay.
        """
        import SimpleITK as sitk  # noqa: PLC0415

        case = self.cases[case_idx]
        case_id = case.get("id", f"case_{case_idx}")

        def _arr(key: str) -> np.ndarray | None:
            img = case.get(key)
            if img is None:
                return None
            return sitk.GetArrayFromImage(img)

        t2w_arr = _arr("t2w")
        adc_arr = _arr("adc")
        hbv_arr = _arr("hbv")

        if t2w_arr is None:
            raise ValueError(f"Case {case_id} has no 't2w' image.")

        z = slice_idx if slice_idx is not None else t2w_arr.shape[0] // 2

        n_panels = 1 + sum(x is not None for x in (adc_arr, hbv_arr)) + (1 if adc_arr is not None else 0)
        fig, axes = plt.subplots(1, n_panels, figsize=(4.5 * n_panels, 4.5))
        axes = np.atleast_1d(axes)
        ax_iter = iter(axes)

        ax = next(ax_iter)
        ax.imshow(_norm(t2w_arr[z], self.norm_lo, self.norm_hi), cmap="gray")
        ax.set_title("T2W")
        ax.axis("off")

        if adc_arr is not None:
            ax = next(ax_iter)
            ax.imshow(_norm(adc_arr[z], self.norm_lo, self.norm_hi), cmap="gray")
            ax.set_title("ADC → T2W")
            ax.axis("off")

        if hbv_arr is not None:
            ax = next(ax_iter)
            ax.imshow(_norm(hbv_arr[z], self.norm_lo, self.norm_hi), cmap="gray")
            ax.set_title("HBV → T2W")
            ax.axis("off")

        if adc_arr is not None:
            ax = next(ax_iter)
            ax.imshow(_norm(t2w_arr[z], self.norm_lo, self.norm_hi), cmap="gray")
            ax.imshow(_norm(adc_arr[z], self.norm_lo, self.norm_hi), cmap="hot", alpha=self.overlay_alpha)
            ax.set_title("T2W + ADC overlay")
            ax.axis("off")

        fig.suptitle(f"{case_id} — slice z={z}", fontsize=12)
        fig.tight_layout()
        return fig

    def show(self, slice_idx: int | None = None) -> None:
        """Show one figure per case."""
        for i in range(len(self.cases)):
            fig = self.figure(case_idx=i, slice_idx=slice_idx)
            plt.show()
            plt.close(fig)

    def alignment_report(self) -> None:
        """Print a geometry comparison table for every case in *self.cases*."""
        def _geo(img) -> dict:
            return {
                "size": img.GetSize(),
                "spacing": tuple(round(s, 3) for s in img.GetSpacing()),
                "origin": tuple(round(o, 2) for o in img.GetOrigin()),
            }

        for case in self.cases:
            case_id = case.get("id", "?")
            print(f"=== {case_id} ===")
            for seq in ("t2w", "adc", "hbv"):
                img = case.get(seq)
                if img is not None:
                    print(f"  {seq}: {_geo(img)}")
            print()


# ---------------------------------------------------------------------------
# Public class 2: CropViewer
# ---------------------------------------------------------------------------

class CropViewer:
    """Visualize crop boxes and cropped images for one aligned bpMRI case.

    Parameters
    ----------
    t2w_path, adc_path, hbv_path : Path or str
        Paths to the aligned sequences (MHA / NIfTI).  ``adc_path`` and
        ``hbv_path`` are optional; pass ``None`` for T2W-only cases.
    gland_path : Path or str
        Whole-gland segmentation mask.
    lesion_path : Path or str or None
        Lesion mask (positive cases only).
    crop_size : int
        Crop size in pixels (default 128).
    stride : int
        Stride used for stride-crop box overlay (default 64).
    random_samples : int
        Number of random boxes to draw (default 5).
    random_seed : int or None
        Seed for reproducible random boxes.
    crops_dir : Path or str or None
        Directory containing saved PNG crops (output of ``CROPro.run()``).
        When supplied, :meth:`show_crops` can display the actual saved images.

    Examples
    --------
    >>> from cropro.visualization import CropViewer
    >>> viewer = CropViewer(
    ...     t2w_path="…/_t2w.mha",
    ...     adc_path="…/_adc.mha",
    ...     hbv_path="…/_hbv.mha",
    ...     gland_path="…/_gland.nii.gz",
    ...     lesion_path="…/_lesion.nii.gz",
    ...     crops_dir="dataset/cropro/…",
    ... )
    >>> viewer.show_boxes(strategies=["center", "stride", "random"])
    >>> viewer.show_crops()
    """

    GLAND_COLOR = "#00E5FF"   # cyan
    LESION_COLOR = "#FF1744"  # vivid red

    def __init__(
        self,
        t2w_path: Path | str,
        *,
        adc_path: Path | str | None = None,
        hbv_path: Path | str | None = None,
        gland_path: Path | str | None = None,
        lesion_path: Path | str | None = None,
        crop_size: int = 128,
        stride: int = 64,
        random_samples: int = 5,
        random_seed: int | None = 42,
        crops_dir: Path | str | None = None,
        norm_lo: float = 1.0,
        norm_hi: float = 99.0,
        use_cropro_normalization: bool = True,
        normalized_image: bool = False,
        do_normalization: bool = True,
        t2w_normalization_method: str = "autoref",
        adc_normalization_method: str = "percentile",
        hbv_normalization_method: str = "percentile",
        min_percentile: float = 0.5,
        max_percentile: float = 99.5,
        adc_min_percentile: float | None = None,
        adc_max_percentile: float | None = None,
        hbv_min_percentile: float | None = None,
        hbv_max_percentile: float | None = None,
        normalized_vmaxNumber: float = 242.0,
    ) -> None:
        self.t2w_path = Path(t2w_path)
        self.adc_path = Path(adc_path) if adc_path else None
        self.hbv_path = Path(hbv_path) if hbv_path else None
        self.gland_path = Path(gland_path) if gland_path else None
        self.lesion_path = Path(lesion_path) if lesion_path else None
        self.crop_size = crop_size
        self.stride = stride
        self.random_samples = random_samples
        self.random_seed = random_seed
        self.crops_dir = Path(crops_dir) if crops_dir else None
        self.norm_lo = norm_lo
        self.norm_hi = norm_hi
        self.use_cropro_normalization = use_cropro_normalization
        self.normalized_image = normalized_image
        self.do_normalization = do_normalization
        self.t2w_normalization_method = t2w_normalization_method
        self.adc_normalization_method = adc_normalization_method
        self.hbv_normalization_method = hbv_normalization_method
        self.min_percentile = min_percentile
        self.max_percentile = max_percentile
        self.adc_min_percentile = adc_min_percentile if adc_min_percentile is not None else min_percentile
        self.adc_max_percentile = adc_max_percentile if adc_max_percentile is not None else max_percentile
        self.hbv_min_percentile = hbv_min_percentile if hbv_min_percentile is not None else min_percentile
        self.hbv_max_percentile = hbv_max_percentile if hbv_max_percentile is not None else max_percentile
        self.normalized_vmaxNumber = float(normalized_vmaxNumber)

        # Cache normalization outputs/windowing for repeated plotting of same slices.
        self._display_norm_cache: dict[tuple[str, int], tuple[np.ndarray, float | None, float | None]] = {}

        # Loaded lazily
        self._t2w: np.ndarray | None = None
        self._adc: np.ndarray | None = None
        self._hbv: np.ndarray | None = None
        self._gland: np.ndarray | None = None
        self._lesion: np.ndarray | None = None

    def _method_for_modality(self, modality: str) -> str:
        modality = modality.upper()
        if modality == "T2W":
            return self.t2w_normalization_method
        if modality == "ADC":
            return self.adc_normalization_method
        if modality == "HBV":
            return self.hbv_normalization_method
        raise ValueError(f"Unknown modality {modality!r}.")

    def _percentiles_for_modality(self, modality: str) -> tuple[float, float]:
        modality = modality.upper()
        if modality == "T2W":
            return self.min_percentile, self.max_percentile
        if modality == "ADC":
            return self.adc_min_percentile, self.adc_max_percentile
        if modality == "HBV":
            return self.hbv_min_percentile, self.hbv_max_percentile
        raise ValueError(f"Unknown modality {modality!r}.")

    def _source_path_for_modality(self, modality: str) -> Path | None:
        modality = modality.upper()
        if modality == "T2W":
            return self.t2w_path
        if modality == "ADC":
            return self.adc_path
        if modality == "HBV":
            return self.hbv_path
        return None

    def _normalize_for_display(
        self,
        modality: str,
        image_slice: np.ndarray,
        *,
        slice_idx: int,
    ) -> tuple[np.ndarray, float | None, float | None]:
        """Apply CROPro-consistent modality normalization for visualization.

        This mirrors the high-level save behavior:
        - T2W: normalized_image -> fixed [0, normalized_vmaxNumber]; else use
          configured strategy when do_normalization=True.
        - ADC/HBV: use configured strategy when do_normalization=True; otherwise
          apply percentile windowing (display-only), matching CROPro defaults.
        """
        key = (modality.upper(), int(slice_idx))
        cached = self._display_norm_cache.get(key)
        if cached is not None:
            return cached

        if not self.use_cropro_normalization:
            normalized = (_norm(image_slice, self.norm_lo, self.norm_hi), None, None)
            self._display_norm_cache[key] = normalized
            return normalized

        from .cropping.normalizers import NormalizationContext, get_normalizer  # noqa: PLC0415

        modality_upper = modality.upper()
        source_path = self._source_path_for_modality(modality_upper)

        if modality_upper == "T2W" and self.normalized_image:
            normalized = (
                image_slice.astype(np.float32),
                0.0,
                float(self.normalized_vmaxNumber),
            )
            self._display_norm_cache[key] = normalized
            return normalized

        if modality_upper in {"ADC", "HBV"} and not self.do_normalization:
            method = "percentile"
        elif self.do_normalization:
            method = self._method_for_modality(modality_upper)
        else:
            normalized = (image_slice.astype(np.float32), None, None)
            self._display_norm_cache[key] = normalized
            return normalized

        min_perc, max_perc = self._percentiles_for_modality(modality_upper)
        context = NormalizationContext(
            source_path=source_path,
            min_percentile=float(min_perc),
            max_percentile=float(max_perc),
            vmax_number=float(self.normalized_vmaxNumber),
        )
        array, vmin, vmax = get_normalizer(method).normalize(image_slice, context)
        normalized = (array.astype(np.float32), float(vmin), float(vmax))
        self._display_norm_cache[key] = normalized
        return normalized

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load all images from disk (idempotent)."""
        if self._t2w is None:
            self._t2w = _read_sitk_array(self.t2w_path)
        if self._adc is None and self.adc_path:
            self._adc = _read_sitk_array(self.adc_path)
        if self._hbv is None and self.hbv_path:
            self._hbv = _read_sitk_array(self.hbv_path)
        if self._gland is None and self.gland_path:
            self._gland = _read_sitk_array(self.gland_path)
        if self._lesion is None and self.lesion_path:
            self._lesion = _read_sitk_array(self.lesion_path)

    def _best_slice(self) -> int:
        """Return the slice index with the most lesion area (or middle slice)."""
        self._load()
        if self._lesion is not None:
            areas = (self._lesion >= 1).reshape(self._lesion.shape[0], -1).sum(axis=1)
            if areas.max() > 0:
                return int(areas.argmax())
        if self._gland is not None:
            areas = (self._gland >= 1).reshape(self._gland.shape[0], -1).sum(axis=1)
            if areas.max() > 0:
                return int(areas.argmax())
        return self._t2w.shape[0] // 2

    # ------------------------------------------------------------------
    # Strategy box computation
    # ------------------------------------------------------------------

    def _get_boxes(
        self,
        strategy: str,
        slice_idx: int,
    ) -> list[tuple[int, int, int, int]]:
        """Compute crop boxes for *strategy* on *slice_idx*.

        Returns list of (x1, y1, x2, y2) in image (col, row) pixel coords.
        """
        self._load()
        gland_slice = self._gland[slice_idx] if self._gland is not None else None
        if gland_slice is None:
            return []

        if strategy == "center":
            return _center_boxes(gland_slice, self.crop_size)
        elif strategy == "stride":
            return _stride_boxes(gland_slice, self.crop_size, self.stride)
        elif strategy == "random":
            return _random_boxes(
                gland_slice, self.crop_size, self.random_samples, seed=self.random_seed
            )
        else:
            raise ValueError(f"Unknown strategy '{strategy}'. Choose from: center, stride, random.")

    # ------------------------------------------------------------------
    # Public visualization methods
    # ------------------------------------------------------------------

    def show_boxes(
        self,
        strategies: Sequence[str] = ("center", "stride", "random"),
        slice_idx: int | None = None,
        show_modalities: bool = True,
    ) -> plt.Figure:
        """Draw crop boxes for the requested strategies on the full T2W slice.

        If ``show_modalities=True`` (default), also shows ADC and HBV panels
        side-by-side so you can verify spatial alignment across sequences.

        Parameters
        ----------
        strategies : sequence of str
            Strategies to overlay.  One or more of ``"center"``,
            ``"stride"``, ``"random"``.
        slice_idx : int or None
            Which slice to use.  ``None`` auto-selects the slice with the
            most lesion area (or the middle slice).
        show_modalities : bool
            When True, adds ADC and HBV panels beside the T2W + boxes panel.

        Returns
        -------
        matplotlib.figure.Figure
        """
        self._load()
        z = slice_idx if slice_idx is not None else self._best_slice()
        t2w_slice, t2w_vmin, t2w_vmax = self._normalize_for_display(
            "T2W", self._t2w[z], slice_idx=z
        )

        # Modality panels: T2W+boxes, ADC, HBV
        modality_data: list[tuple[str, np.ndarray]] = []
        if show_modalities and self._adc is not None:
            adc_slice, adc_vmin, adc_vmax = self._normalize_for_display(
                "ADC", self._adc[z], slice_idx=z
            )
            modality_data.append(("ADC", adc_slice, adc_vmin, adc_vmax))
        if show_modalities and self._hbv is not None:
            hbv_slice, hbv_vmin, hbv_vmax = self._normalize_for_display(
                "HBV", self._hbv[z], slice_idx=z
            )
            modality_data.append(("HBV", hbv_slice, hbv_vmin, hbv_vmax))

        n_cols = 1 + len(modality_data)
        fig, axes = plt.subplots(1, n_cols, figsize=(5.5 * n_cols, 5.5))
        axes = np.atleast_1d(axes)

        # --- Panel 0: T2W + all strategy boxes + mask contours ---
        ax = axes[0]
        ax.imshow(t2w_slice, cmap="gray", vmin=t2w_vmin, vmax=t2w_vmax)
        if self._gland is not None:
            ax.contour(
                self._gland[z] >= 1,
                levels=[0.5],
                colors=self.GLAND_COLOR,
                linewidths=1.2,
            )
        if self._lesion is not None:
            ax.contour(
                self._lesion[z] >= 1,
                levels=[0.5],
                colors=self.LESION_COLOR,
                linewidths=1.6,
            )

        legend_handles = []
        for strat in strategies:
            color = _STRATEGY_COLORS.get(strat, "#FFFFFF")
            boxes = self._get_boxes(strat, z)
            for x1, y1, x2, y2 in boxes:
                rect = mpatches.Rectangle(
                    (x1, y1),
                    x2 - x1,
                    y2 - y1,
                    linewidth=1.5,
                    edgecolor=color,
                    facecolor="none",
                    linestyle="--" if strat == "random" else "-",
                )
                ax.add_patch(rect)
            legend_handles.append(
                mpatches.Patch(edgecolor=color, facecolor="none", label=f"{strat} ({len(boxes)})")
            )

        # Mask legend entries
        legend_handles.append(
            mpatches.Patch(edgecolor=self.GLAND_COLOR, facecolor="none", label="gland")
        )
        if self._lesion is not None:
            legend_handles.append(
                mpatches.Patch(edgecolor=self.LESION_COLOR, facecolor="none", label="lesion")
            )

        ax.legend(handles=legend_handles, loc="upper right", fontsize=8, framealpha=0.7)
        ax.set_title(f"T2W slice z={z}  |  crop boxes", fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])

        # --- Panels 1+: ADC / HBV with same contours ---
        for ax, (mod_name, mod_slice, mod_vmin, mod_vmax) in zip(
            axes[1:], modality_data, strict=False
        ):
            ax.imshow(mod_slice, cmap="gray", vmin=mod_vmin, vmax=mod_vmax)
            if self._gland is not None:
                ax.contour(
                    self._gland[z] >= 1,
                    levels=[0.5],
                    colors=self.GLAND_COLOR,
                    linewidths=1.2,
                )
            if self._lesion is not None:
                ax.contour(
                    self._lesion[z] >= 1,
                    levels=[0.5],
                    colors=self.LESION_COLOR,
                    linewidths=1.6,
                )
            ax.set_title(f"{mod_name} (aligned)", fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])

        case_id = self.t2w_path.name.split("_t2w")[0]
        fig.suptitle(f"Case {case_id} — crop box overlay", fontsize=12, fontweight="bold")
        fig.tight_layout()
        return fig

    def show_crops(
        self,
        crops_dir: Path | str | None = None,
        *,
        max_crops: int = 8,
        title_prefix: str = "",
    ) -> plt.Figure | None:
        """Display saved crop PNGs grouped by modality (T2W, ADC, HBV).

        Parameters
        ----------
        crops_dir : Path or str or None
            Override for the crops directory; falls back to ``self.crops_dir``.
        max_crops : int
            Maximum number of crops to show per modality row.
        title_prefix : str
            Optional string prepended to the figure title.

        Returns
        -------
        matplotlib.figure.Figure or None
            ``None`` when no crops were found.
        """
        search_dir = Path(crops_dir) if crops_dir else self.crops_dir
        if search_dir is None or not search_dir.is_dir():
            print("No crops directory supplied or directory does not exist.")
            return None

        modalities = ["T2W", "ADC", "HBV"] if (self.adc_path or self.hbv_path) else ["T2W"]
        crops_per_mod: dict[str, list[Path]] = {}
        for mod in modalities:
            found = sorted(search_dir.rglob(f"*_{mod}.png"))
            crops_per_mod[mod] = found[:max_crops]

        n_present = sum(1 for v in crops_per_mod.values() if v)
        if n_present == 0:
            print(f"No crop PNGs found under {search_dir}")
            return None

        n_cols = max(len(v) for v in crops_per_mod.values() if v) or 1
        n_rows = n_present
        fig, axes = plt.subplots(
            n_rows, n_cols, figsize=(2.8 * n_cols, 2.8 * n_rows), squeeze=False
        )

        row = 0
        for mod in modalities:
            paths = crops_per_mod.get(mod, [])
            if not paths:
                continue
            for col, path in enumerate(paths):
                ax = axes[row][col]
                img = _load_gray(path)
                ax.imshow(img, cmap="gray", vmin=0.0, vmax=1.0)
                ax.set_title(path.name, fontsize=6)
                ax.set_xticks([])
                ax.set_yticks([])
            # hide empty columns
            for col in range(len(paths), n_cols):
                axes[row][col].set_visible(False)
            # row label
            axes[row][0].set_ylabel(mod, fontsize=10, rotation=0, labelpad=30, va="center")
            row += 1

        case_id = self.t2w_path.name.split("_t2w")[0]
        title = f"{title_prefix}{case_id} — saved crops"
        fig.suptitle(title, fontsize=12, fontweight="bold")
        fig.tight_layout()
        return fig

    def show_alignment(self, slice_idx: int | None = None) -> plt.Figure:
        """Show T2W, ADC, HBV slices side-by-side to verify alignment.

        A 1-row panel of each modality with gland/lesion contours drawn on
        every panel so any misalignment is immediately visible.

        Returns
        -------
        matplotlib.figure.Figure
        """
        self._load()
        z = slice_idx if slice_idx is not None else self._best_slice()

        seq_items: list[tuple[str, np.ndarray]] = [("T2W", self._t2w)]
        if self._adc is not None:
            seq_items.append(("ADC", self._adc))
        if self._hbv is not None:
            seq_items.append(("HBV", self._hbv))

        n = len(seq_items)
        fig, axes = plt.subplots(1, n, figsize=(5.0 * n, 5.0))
        axes = np.atleast_1d(axes)

        for ax, (mod, arr) in zip(axes, seq_items, strict=False):
            norm_slice, vmin, vmax = self._normalize_for_display(mod, arr[z], slice_idx=z)
            ax.imshow(norm_slice, cmap="gray", vmin=vmin, vmax=vmax)
            if self._gland is not None:
                ax.contour(
                    self._gland[z] >= 1,
                    levels=[0.5],
                    colors=self.GLAND_COLOR,
                    linewidths=1.2,
                )
            if self._lesion is not None:
                ax.contour(
                    self._lesion[z] >= 1,
                    levels=[0.5],
                    colors=self.LESION_COLOR,
                    linewidths=1.6,
                )
            ax.set_title(f"{mod}  z={z}", fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])

        case_id = self.t2w_path.name.split("_t2w")[0]
        fig.suptitle(
            f"Case {case_id} — sequence alignment check (gland=cyan, lesion=red)",
            fontsize=11,
            fontweight="bold",
        )
        fig.tight_layout()
        return fig
