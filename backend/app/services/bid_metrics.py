"""입찰 실험 통계 공통 함수."""

from __future__ import annotations

import math


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """이항 비율의 Wilson 95% 신뢰구간(%).

    표본이 작으면 구간이 넓어져 arm 우열을 섣불리 단정하지 못하게 한다.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half) * 100.0,
            min(1.0, center + half) * 100.0)
