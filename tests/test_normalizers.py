import numpy as np
import pytest

from cropro.cropping.normalizers import (
    GaussianNormalizer,
    NormalizationContext,
    Normalizer,
    available_normalizers,
    get_normalizer,
    register_normalizer,
)


def _context() -> NormalizationContext:
    return NormalizationContext(
        source_path=None, min_percentile=0.5, max_percentile=99.5, vmax_number=242
    )


def test_registry_exposes_builtin_strategies():
    assert set(available_normalizers()) == {"percentile", "autoref", "gaussian", "zscore_clip"}


def test_get_normalizer_returns_strategy_instance():
    assert isinstance(get_normalizer("gaussian"), GaussianNormalizer)


def test_get_unknown_normalizer_raises():
    with pytest.raises(ValueError, match="Unknown normalization method"):
        get_normalizer("minmax")


def test_autoref_is_t2w_only():
    assert get_normalizer("autoref").supported_modalities == frozenset({"T2W"})


def test_gaussian_normalizes_to_unit_window():
    array = np.arange(16, dtype=np.float32).reshape(4, 4)
    out, vmin, vmax = get_normalizer("gaussian").normalize(array, _context())
    assert (vmin, vmax) == (0.0, 1.0)
    assert out.dtype == np.float32
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_gaussian_constant_image_returns_zeros():
    array = np.full((4, 4), 5.0, dtype=np.float32)
    out, vmin, vmax = get_normalizer("gaussian").normalize(array, _context())
    assert np.all(out == 0.0)
    assert (vmin, vmax) == (0.0, 1.0)


def test_zscore_clip_is_zero_mean():
    rng = np.random.default_rng(0)
    array = rng.normal(100, 20, size=(8, 8)).astype(np.float32)
    out, _, _ = get_normalizer("zscore_clip").normalize(array, _context())
    assert abs(float(out.mean())) < 1e-5


def test_register_requires_name():
    with pytest.raises(ValueError, match="non-empty 'name'"):

        @register_normalizer
        class _Nameless(Normalizer):
            def normalize(self, image_array, context):
                return image_array, 0.0, 1.0
