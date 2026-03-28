from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_numeric_search_space(value: int | float) -> list[int | float]:
    if isinstance(value, bool):
        return [value]

    low = value * 0.7
    high = value * 1.3
    steps = 6
    if isinstance(value, int):
        candidates = sorted({max(1, round(low + (high - low) * idx / steps)) for idx in range(steps + 1)})
        return [int(candidate) for candidate in candidates]

    candidates = sorted({round(low + (high - low) * idx / steps, 4) for idx in range(steps + 1)})
    return [float(candidate) for candidate in candidates]


def build_param_space(defaults: Mapping[str, Any]) -> dict[str, list[Any]]:
    param_space: dict[str, list[Any]] = {}
    for key, value in defaults.items():
        if isinstance(value, bool):
            param_space[key] = [True, False]
        elif isinstance(value, (int, float)):
            param_space[key] = build_numeric_search_space(value)
        else:
            param_space[key] = [value]
    return param_space
