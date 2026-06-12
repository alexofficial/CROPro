"""Strategy registry for per-modality intensity normalization.

Each normalization recipe is encapsulated in a :class:`Normalizer` strategy
class and registered under a short name (``percentile``, ``autoref``,
``gaussian``, ``zscore_clip``). The file-writing code resolves the strategy for
a modality with :func:`get_normalizer` instead of carrying a per-method
``if/elif`` chain, so adding a new method only means writing one class and
decorating it with :func:`register_normalizer`.

Heavy imaging dependencies (SimpleITK, pyAutoRef) are imported lazily inside the
strategies that need them, keeping ``import cropro`` lightweight.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# AutoRef runs object detection over a whole 3D T2W volume, which is expensive,
# so the derived linear scaling is cached per source volume (keyed by file path)
# and reused for every crop taken from that volume.
_AUTOREF_COEFF_CACHE: dict[str, tuple[float, float]] = {}


@dataclass(slots=True)
class NormalizationContext:
    """Everything a :class:`Normalizer` may need beyond the crop itself.

    Attributes
    ----------
    source_path:
        Path to the full 3D source volume for the modality being saved. Used by
        strategies that derive statistics from the whole volume (``percentile``,
        ``autoref``) rather than from the individual crop.
    min_percentile, max_percentile:
        Percentile clip/window bounds shared across strategies.
    vmax_number:
        Display window maximum used by intensity-preserving strategies.
    """

    source_path: str | Path | None
    min_percentile: float
    max_percentile: float
    vmax_number: float


class Normalizer(ABC):
    """Base strategy: turn a crop into ``(array_to_save, vmin, vmax)``."""

    #: Registry key for this strategy.
    name: str = ""
    #: Modalities this strategy may be applied to. ``None`` means any modality.
    supported_modalities: frozenset[str] | None = None

    @abstractmethod
    def normalize(
        self, image_array: np.ndarray, context: NormalizationContext
    ) -> tuple[np.ndarray, float, float]:
        """Return the array to write plus its display window ``(vmin, vmax)``."""


_REGISTRY: dict[str, type[Normalizer]] = {}


def register_normalizer(cls: type[Normalizer]) -> type[Normalizer]:
    """Class decorator that registers a :class:`Normalizer` by its ``name``."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a non-empty 'name'.")
    _REGISTRY[cls.name] = cls
    return cls


def get_normalizer(name: str) -> Normalizer:
    """Resolve a registered :class:`Normalizer` strategy by name."""
    try:
        return _REGISTRY[name]()
    except KeyError as exc:
        raise ValueError(
            f"Unknown normalization method {name!r}. "
            f"Expected one of {available_normalizers()}."
        ) from exc


def available_normalizers() -> tuple[str, ...]:
    """Return the registered normalization method names, sorted."""
    return tuple(sorted(_REGISTRY))


@register_normalizer
class PercentileNormalizer(Normalizer):
    """Intensity-preserving windowing from the full source volume.

    Keeps the raw crop values and only derives a display window from the
    ``[min_percentile, max_percentile]`` range of the whole 3D source volume.
    """

    name = "percentile"

    def normalize(
        self, image_array: np.ndarray, context: NormalizationContext
    ) -> tuple[np.ndarray, float, float]:
        import SimpleITK as sitk

        volume = sitk.GetArrayFromImage(sitk.ReadImage(str(context.source_path)))
        vmin = float(np.percentile(volume, context.min_percentile))
        vmax = float(np.percentile(volume, context.max_percentile))
        return image_array, vmin, vmax


@register_normalizer
class GaussianNormalizer(Normalizer):
    """Gaussian (z-score) normalization of the crop.

    Computes ``(x - mean) / std`` on the crop, clips to ``[-3, 3]`` (about
    99.7% of a normal distribution) and rescales to ``[0, 1]`` for display.
    """

    name = "gaussian"

    def normalize(
        self, image_array: np.ndarray, context: NormalizationContext
    ) -> tuple[np.ndarray, float, float]:
        image_array = image_array.astype(np.float32)
        mean = float(np.mean(image_array))
        std = float(np.std(image_array))
        if std == 0:
            return np.zeros_like(image_array, dtype=np.float32), 0.0, 1.0

        z_scores = (image_array - mean) / std
        clipped = np.clip(z_scores, -3, 3)
        normalized_array = ((clipped + 3) / 6).astype(np.float32)
        return normalized_array, 0.0, 1.0


@register_normalizer
class ZScoreClipNormalizer(Normalizer):
    """Instance-wise z-score normalization with percentile clipping.

    Mirrors the PI-CAI state-of-the-art recipe used by the official
    ``picai_baseline`` U-Net (and nnU-Net's MR scheme): each sequence is
    normalized independently by clipping intensities to the
    ``[min_percentile, max_percentile]`` range (SOTA uses 0.5 and 99.5) and then
    applying z-score normalization ``(x - mean) / std`` on the clipped crop.
    """

    name = "zscore_clip"

    def normalize(
        self, image_array: np.ndarray, context: NormalizationContext
    ) -> tuple[np.ndarray, float, float]:
        image_array = image_array.astype(np.float32)

        lower = np.percentile(image_array, context.min_percentile)
        upper = np.percentile(image_array, context.max_percentile)
        clipped = np.clip(image_array, lower, upper)

        mean = float(np.mean(clipped))
        std = float(np.std(clipped))
        if std == 0:
            return np.zeros_like(clipped, dtype=np.float32), 0.0, 1.0

        normalized_array = ((clipped - mean) / std).astype(np.float32)
        return normalized_array, float(normalized_array.min()), float(normalized_array.max())


@register_normalizer
class AutorefNormalizer(Normalizer):
    """AutoRef (fat/muscle reference) normalization, T2W only.

    AutoRef (``pyAutoRef``) detects fat and muscle reference tissue across the
    whole 3D T2W volume and applies a global linear scaling so fat and muscle
    map to fixed reference intensities. Because that detection needs the full
    volume (not a single crop), AutoRef is run once on the source T2W volume, the
    equivalent linear map ``out = a * x + b`` is fitted and cached, then applied
    to each crop.
    """

    name = "autoref"
    supported_modalities = frozenset({"T2W"})

    def normalize(
        self, image_array: np.ndarray, context: NormalizationContext
    ) -> tuple[np.ndarray, float, float]:
        a, b = _autoref_linear_coeffs(str(context.source_path))
        normalized_array = (a * image_array.astype(np.float32) + b).astype(np.float32)
        return normalized_array, 0.0, float(context.vmax_number)


def _autoref_linear_coeffs(t2w_path: str) -> tuple[float, float]:
    """Return the cached AutoRef linear map ``(a, b)`` for a T2W volume.

    Runs AutoRef on the full volume once and fits a global linear map
    ``normalized = a * original + b`` against it. AutoRef applies an N4 bias
    correction before the fat/muscle linear scaling, so the map is an
    approximation; over a small prostate crop the bias field is near-constant,
    which makes the global linear fit accurate enough to normalize crops without
    re-running detection per crop.
    """
    key = str(t2w_path)
    cached = _AUTOREF_COEFF_CACHE.get(key)
    if cached is not None:
        return cached

    import SimpleITK as sitk

    try:
        from pyAutoRef import autoref
    except ImportError as exc:
        raise ImportError(
            "normalization method 'autoref' requires the 'pyAutoRef' package. "
            "Install it with: uv add pyAutoRef  (or pip install pyAutoRef)."
        ) from exc

    # Cast to float32: pyAutoRef's N4 bias-field correction does not support
    # integer pixel types (e.g. T2W stored as 16-bit unsigned int) in 3D.
    image = sitk.Cast(sitk.ReadImage(str(t2w_path)), sitk.sitkFloat32)
    try:
        normalized_image = autoref(image)
    except ValueError as exc:
        # Some volumes can fail inside pyAutoRef detection with
        # "attempt to get argmax of an empty sequence". Keep the pipeline
        # running by using identity normalization for that case.
        if "argmax of an empty sequence" in str(exc):
            coeffs = (1.0, 0.0)
            _AUTOREF_COEFF_CACHE[key] = coeffs
            return coeffs
        raise

    original = sitk.GetArrayFromImage(image).astype(np.float64).ravel()
    normalized = sitk.GetArrayFromImage(normalized_image).astype(np.float64).ravel()

    # Guard against unexpected empty/invalid outputs from upstream normalization.
    if original.size == 0 or normalized.size == 0:
        coeffs = (1.0, 0.0)
        _AUTOREF_COEFF_CACHE[key] = coeffs
        return coeffs
    finite = np.isfinite(normalized)
    if not np.any(finite):
        coeffs = (1.0, 0.0)
        _AUTOREF_COEFF_CACHE[key] = coeffs
        return coeffs
    if not np.all(finite):
        original = original[finite]
        normalized = normalized[finite]

    # Subsample for a fast, stable least-squares fit on large volumes.
    if original.size > 200_000:
        idx = np.linspace(0, original.size - 1, 200_000).astype(np.int64)
        original = original[idx]
        normalized = normalized[idx]

    a, b = np.polyfit(original, normalized, 1)
    coeffs = (float(a), float(b))
    _AUTOREF_COEFF_CACHE[key] = coeffs
    return coeffs
