"""Regression tests for the ``is_mask`` argument of ``load_resample_itk``.

ADC/HBV (and T2W) are intensity images and must be resampled with B-spline
interpolation, i.e. ``is_mask=False``. A prior bug passed ``slice_number``
positionally into ``is_mask`` (a truthy int -> ``True``), so intensity images
were resampled as segmentation masks with nearest-neighbour interpolation.

These tests parse the cropping strategy modules and assert that every
``load_resample_itk`` call that loads an ADC/HBV/T2W image passes
``is_mask=False`` explicitly, and that mask loads pass ``is_mask=True``.
"""

import ast
from pathlib import Path

import pytest

CROPPING_DIR = Path(__file__).resolve().parents[1] / "src" / "cropro" / "cropping"

STRATEGY_FILES = [
    "negativeCenterC.py",
    "negativeRandomC.py",
    "negativeStrideC.py",
    "positiveCenterC.py",
    "positiveRandomC.py",
    "positiveStrideC.py",
    "centerCropCommon.py",
]

# Attribute names that identify an intensity-image path argument.
INTENSITY_PATH_NAMES = {
    "orig_img_path_t2w",
    "orig_img_path_adc",
    "orig_img_path_hbv",
}


def _load_resample_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "load_resample_itk"
    ]


def _is_mask_keyword(call: ast.Call) -> ast.keyword | None:
    for kw in call.keywords:
        if kw.arg == "is_mask":
            return kw
    return None


def _references_intensity_path(call: ast.Call) -> bool:
    """True if the first positional argument resolves to an intensity-image path."""
    if not call.args:
        return False
    first = call.args[0]
    for node in ast.walk(first):
        if isinstance(node, ast.Attribute) and node.attr in INTENSITY_PATH_NAMES:
            return True
    return False


@pytest.mark.parametrize("filename", STRATEGY_FILES)
def test_intensity_loads_pass_is_mask_false(filename):
    source = (CROPPING_DIR / filename).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Center strategies delegate to centerCropCommon, so some files
    # legitimately contain no direct load_resample_itk calls.
    for call in _load_resample_calls(tree):
        kw = _is_mask_keyword(call)
        # Every call must pass is_mask as a keyword (never positionally).
        assert kw is not None, (
            f"{filename}:{call.lineno} calls load_resample_itk without an "
            "explicit is_mask keyword"
        )
        assert isinstance(kw.value, ast.Constant), (
            f"{filename}:{call.lineno} passes a non-literal is_mask value"
        )
        if _references_intensity_path(call):
            assert kw.value.value is False, (
                f"{filename}:{call.lineno} loads an intensity image (ADC/HBV/T2W) "
                "but does not pass is_mask=False"
            )


def test_no_positional_is_mask_anywhere():
    """No strategy may pass is_mask positionally (the original bug)."""
    total_calls = 0
    for filename in STRATEGY_FILES:
        source = (CROPPING_DIR / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for call in _load_resample_calls(tree):
            total_calls += 1
            # Signature is load_resample_itk(self/obj, filename, is_mask=...),
            # so a bound call should have at most one positional arg (the path).
            assert len(call.args) <= 1, (
                f"{filename}:{call.lineno} passes is_mask positionally; "
                "use the is_mask= keyword instead"
            )
    # Guard against the audit silently passing if the calls move or are renamed.
    assert total_calls > 0, "No load_resample_itk calls found across strategies"
