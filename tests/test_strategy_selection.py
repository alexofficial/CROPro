"""Tests for crop strategy registry dispatch.

These lock the mapping from (patient_status, crop_method) to the concrete
strategy executor so the registry stays behaviour-compatible with the original
hard-coded dispatch in ``croppingCrontrollerClass``.
"""

import pytest

from cropro.cropping import strategy_registry
from cropro.cropping.negativeCenterC import negativeCenterC
from cropro.cropping.negativeRandomC import negativeRandomC
from cropro.cropping.negativeStrideC import negativeStrideC
from cropro.cropping.positiveCenterC import positiveCenterC
from cropro.cropping.positiveRandomC import positiveRandomC
from cropro.cropping.positiveStrideC import positiveStrideC


@pytest.mark.parametrize(
    ("patient_status", "crop_method", "expected"),
    [
        ("negative", "center", negativeCenterC.negativeCenter),
        ("negative", "random", negativeRandomC.negativeRandom),
        ("negative", "stride", negativeStrideC.negativeStride),
        ("unknown", "center", negativeCenterC.negativeCenter),
        ("unknown", "random", negativeRandomC.negativeRandom),
        ("unknown", "stride", negativeStrideC.negativeStride),
        ("positive", "center", positiveCenterC.positiveCenter),
        ("positive", "random", positiveRandomC.positiveRandom),
        ("positive", "stride", positiveStrideC.positiveStride),
    ],
)
def test_get_strategy_returns_expected_executor(patient_status, crop_method, expected):
    assert strategy_registry.get_strategy(patient_status, crop_method) is expected


def test_get_strategy_unknown_combination_raises():
    with pytest.raises(ValueError, match="No crop strategy registered"):
        strategy_registry.get_strategy("positive", "nonexistent")


def test_get_strategy_unknown_status_raises():
    with pytest.raises(ValueError, match="No crop strategy registered"):
        strategy_registry.get_strategy("invalid", "center")
