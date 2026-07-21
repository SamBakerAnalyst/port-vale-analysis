from __future__ import annotations


def format_metric_value(value: float | None) -> str:
    if value is None:
        return "-"
    rounded = round(value)
    if abs(value - rounded) < 0.01:
        return str(int(rounded))
    if abs(value) < 10:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_percentile_label(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{int(round(value))}%"


def percentile_ordinal(value: float | None) -> str:
    return format_percentile_label(value)


def percentile_colors(percentile: float | None) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    if percentile is None:
        return (148, 163, 184), (241, 245, 249), (100, 116, 139)
    if percentile >= 80:
        return (30, 107, 58), (220, 252, 231), (22, 101, 52)
    if percentile >= 60:
        return (56, 142, 90), (236, 253, 245), (21, 128, 61)
    if percentile >= 40:
        return (202, 138, 4), (254, 249, 195), (161, 98, 7)
    if percentile >= 25:
        return (194, 97, 22), (255, 237, 213), (154, 52, 18)
    return (220, 38, 38), (254, 226, 226), (185, 28, 28)
