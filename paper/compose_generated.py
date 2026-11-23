"""Composite the two generated conceptual illustrations into paper figures.

The raw renders in paper/figures/raw/ carry labels at roughly 4 pt once placed
at the 3.24 in IEEE column width, which is below the legible floor. This script
masks those labels, crops dead margin and the one arrow that leads nowhere, and
re-sets the text in the same serif face the other figures use, so all six
figures read as one set.

Only the two purely schematic illustrations go through here. Figures built from
real pipeline artifacts are drawn directly by make_figs.py and are never passed
through an image model.

Run from the repo root:  .venv/Scripts/python.exe paper/compose_generated.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = Path(__file__).resolve().parent
RAW = OUT / "figures" / "raw"
DPI = 600
COL_W = 3.30

NAVY = "#1F3864"
GREY = "#6B7280"

plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]

LABEL_FS = 5.6
NOTE_FS = 4.8


def compose(src, dst, crop, masks, labels, notes=()):
    """Mask, crop and re-label one generated illustration.

    crop   -- (x0, y0, x1, y1) in source pixels
    masks  -- rects in source pixels to paint out before cropping
    labels -- (x, y, text) in source pixels, centred, serif at LABEL_FS
    notes  -- (x, y, text, ha) smaller italic annotations
    """
    img = plt.imread(RAW / src)
    x0, y0, x1, y1 = crop
    w, h = x1 - x0, y1 - y0

    fig = plt.figure(figsize=(COL_W, COL_W * h / w))
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img, zorder=1)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.axis("off")

    for mx0, my0, mx1, my1 in masks:
        ax.add_patch(Rectangle((mx0, my0), mx1 - mx0, my1 - my0,
                               facecolor="white", edgecolor="none", zorder=2))

    for lx, ly, text in labels:
        ax.text(lx, ly, text, ha="center", va="center", fontsize=LABEL_FS,
                color=NAVY, zorder=3, linespacing=1.2, fontweight="bold")

    for nx, ny, text, ha in notes:
        ax.text(nx, ny, text, ha=ha, va="center", fontsize=NOTE_FS,
                color=GREY, style="italic", zorder=3, linespacing=1.2)

    p = OUT / dst
    fig.savefig(p, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"wrote {p}  ({w}x{h} px -> {COL_W * h / w:.2f} in tall "
          f"at {COL_W} in wide)")


# ------------------------------------------------- Fig. 1, the coverage problem
# The raw render carries no text at all, so nothing needs masking; it only needs
# labels and a crop that leaves room for them under the illustration.
compose(
    src="fig1_coverage_raw.png",
    dst="fig1_coverage.png",
    crop=(20, 120, 1520, 905),
    masks=[],
    labels=[
        (253, 862, "Technical document"),
        (829, 862, "What a text-only index reaches"),
        (1365, 640, "Incomplete\nanswer"),
    ],
    notes=[
        (1012, 545, "table:\nnot indexed", "left"),
        (1012, 720, "figure:\nnot indexed", "left"),
    ],
)

# ------------------------------------- Fig. 4, caption retrieves, image generates
# Five labels sit at ~26 px, which is roughly 4 pt at column width. Mask each and
# re-set it at the same centre. The arrow leaving the right edge points at
# nothing, so it is painted out too.
compose(
    src="fig4_deferred_raw.png",
    dst="fig4_deferred.png",
    crop=(40, 115, 1500, 895),
    masks=[
        (1436, 500, 1536, 800),        # the arrow that leads nowhere
        (95, 592, 280, 636),           # visual region
        (515, 367, 795, 410),          # dense factual caption
        (1020, 385, 1285, 428),        # shared vector space
        (505, 730, 792, 774),          # original crop, deferred
        (1085, 808, 1480, 852),        # single grounded generation call
    ],
    labels=[
        (187, 613, "Visual region"),
        (654, 388, "Dense factual caption"),
        (1152, 406, "Shared vector space"),
        (647, 751, "Original crop, deferred"),
        (1240, 830, "Single grounded\ngeneration call"),
    ],
)
