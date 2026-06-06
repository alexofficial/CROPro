"""Registry mapping (patient_status, crop_method) pairs to crop strategy executors.

This decouples the algorithm dispatch from ``croppingControllerClass`` so new
crop strategies can be registered without editing the controller's branching
logic. Each registered executor is called with the controller instance as its
sole argument, preserving the existing ``Class.method(self)`` invocation pattern.
"""

from collections.abc import Callable

from .negativeCenterC import negativeCenterC
from .negativeRandomC import negativeRandomC
from .negativeStrideC import negativeStrideC
from .positiveCenterC import positiveCenterC
from .positiveRandomC import positiveRandomC
from .positiveStrideC import positiveStrideC

# Patient statuses that are treated as "non-positive" by the existing dispatch.
_NEGATIVE_STATUSES = ("negative", "unknown")

# Maps (patient_status, crop_method) -> executor callable taking the controller.
STRATEGY_REGISTRY: dict[tuple[str, str], Callable[[object], None]] = {}


def register_strategy(
    patient_status: str, crop_method: str, executor: Callable[[object], None]
) -> None:
    """Register a crop strategy executor for a (patient_status, crop_method) pair."""
    STRATEGY_REGISTRY[(patient_status, crop_method)] = executor


def _register_defaults() -> None:
    """Register the six built-in crop strategy combinations."""
    for status in _NEGATIVE_STATUSES:
        register_strategy(status, "center", negativeCenterC.negativeCenter)
        register_strategy(status, "random", negativeRandomC.negativeRandom)
        register_strategy(status, "stride", negativeStrideC.negativeStride)

    register_strategy("positive", "center", positiveCenterC.positiveCenter)
    register_strategy("positive", "random", positiveRandomC.positiveRandom)
    register_strategy("positive", "stride", positiveStrideC.positiveStride)


_register_defaults()


def get_strategy(patient_status: str, crop_method: str) -> Callable[[object], None]:
    """Return the executor for a (patient_status, crop_method) pair.

    Raises
    ------
    ValueError
        If no strategy is registered for the given combination.
    """
    try:
        return STRATEGY_REGISTRY[(patient_status, crop_method)]
    except KeyError:
        raise ValueError(
            "No crop strategy registered for "
            f"patient_status={patient_status!r}, crop_method={crop_method!r}"
        ) from None
