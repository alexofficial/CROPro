"""Library entry points for CROPro."""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from .config import CropConfig


class CROPro:
    """Run CROPro cropping from Python code.

    Parameters may be provided either as a :class:`CropConfig` or as keyword
    arguments matching ``CropConfig`` fields.
    """

    def __init__(self, config: CropConfig | None = None, **overrides: Any) -> None:
        if config is not None and overrides:
            values = config.to_dict()
            values.update({key: value for key, value in overrides.items() if value is not None})
            self.config = CropConfig.from_mapping(values)
        elif config is not None:
            self.config = config
        else:
            self.config = CropConfig.from_mapping(
                {key: value for key, value in overrides.items() if value is not None}
            )

        self.arg = self.config

        if self.config.random_seed is not None:
            random.seed(self.config.random_seed)
            np.random.seed(self.config.random_seed)

    def cropro(self) -> None:
        self.run()

    def run(self) -> None:
        # Crop pipeline. For bpMRI, fail fast with an actionable message if the
        # ADC/HBV sequences are not on the T2W grid and on-the-fly resampling is
        # off (cropping misaligned sequences would silently mix anatomy).
        from cropro.resample import check_bpmri_alignment

        check_bpmri_alignment(self.config)

        from cropro.cropping.patientCropC import patientCropC

        patient_crop = patientCropC(self.arg)
        patient_crop.patientCrop()


def run(config: CropConfig | None = None, **overrides: Any) -> None:
    CROPro(config=config, **overrides).run()
