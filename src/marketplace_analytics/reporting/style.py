"""Shared chart style: one restrained palette, recessive axes, consistent annotation.

Categorical colours are used in a fixed order, and text never takes a series colour.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3de"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # blue, orange, aqua, yellow
BLUE, ORANGE = SERIES[0], SERIES[1]

HISTORICAL_SOURCE = "Source: Olist Brazilian E-Commerce public dataset (real historical data)."
SIMULATED_SOURCE = "SIMULATED DATA - synthetic experiment, not real business results."


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT_SECONDARY,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlecolor": TEXT_PRIMARY,
            "axes.titlelocation": "left",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": TEXT_SECONDARY,
            "ytick.color": TEXT_SECONDARY,
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "legend.frameon": False,
            "legend.labelcolor": TEXT_PRIMARY,
            "lines.linewidth": 2,
        }
    )


def new_figure(width: float = 9, height: float = 4.8, ncols: int = 1, nrows: int = 1, **kw):
    apply_style()
    return plt.subplots(nrows, ncols, figsize=(width, height), **kw)


def finish(fig: Figure, title: str, subtitle: str, note: str = HISTORICAL_SOURCE) -> None:
    """Add a headline title, a subtitle stating the population, and a source note.

    Positions are fixed in inches so spacing is identical across figure sizes.
    """
    height = fig.get_figheight()
    fig.text(
        0.01,
        1 - 0.32 / height,
        title,
        ha="left",
        va="baseline",
        fontsize=13,
        fontweight="bold",
        color=TEXT_PRIMARY,
    )
    fig.text(
        0.01,
        1 - 0.58 / height,
        subtitle,
        ha="left",
        va="baseline",
        fontsize=9.5,
        color=TEXT_SECONDARY,
    )
    fig.text(0.01, 0.10 / height, note, ha="left", va="baseline", fontsize=8, color=TEXT_SECONDARY)
    fig.tight_layout(rect=(0, 0.28 / height, 1, 1 - 0.72 / height))


def save(fig: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def pct_axis(ax, axis: str = "y", decimals: int = 0) -> None:
    fmt = PercentFormatter(xmax=1, decimals=decimals)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def thousands_axis(ax, axis: str = "y", prefix: str = "") -> None:
    def fmt(v, _):
        if abs(v) >= 1e6:
            return f"{prefix}{v / 1e6:.1f}M"
        if abs(v) >= 1e3:
            return f"{prefix}{v / 1e3:.0f}k"
        return f"{prefix}{v:.0f}"

    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(FuncFormatter(fmt))
