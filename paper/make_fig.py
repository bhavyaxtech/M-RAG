"""Generate Fig. 4, the M-RAG architecture diagram, at single-column width.

The offline and online paths run side by side rather than stacked, which keeps
the figure near square instead of the 1.6:1 portrait it used to be. At the
3.24 in placement width build_paper.py uses, that is the difference between
5.1 in and roughly 3.1 in of column height.

Run from the repo root:  .venv/Scripts/python.exe paper/make_fig.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]

OUT = Path(__file__).resolve().parent / "fig5_architecture.png"

NAVY = "#1F3864"
BLUE = "#2563EB"
BLUE_FILL = "#DBEAFE"
AMBER = "#B45309"
AMBER_FILL = "#FDE8C8"
GREY = "#6B7280"
GREY_FILL = "#F3F4F6"
INK = "#111827"

W, H = 100.0, 92.0
FIG_W = 3.30
FIG_H = FIG_W * H / W

fig = plt.figure(figsize=(FIG_W, FIG_H))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")
fig.patch.set_facecolor("white")

BOX_FS = 4.5
LBL_FS = 5.4
NOTE_FS = 4.0

LCX, RCX = 24.5, 75.0          # centres of the offline and online columns
COL_W_ = 45.0                  # full-width box inside a column
HALF_W = 21.5                  # side-by-side box inside a column
LX, LRX = LCX - 11.6, LCX + 11.6


def box(cx, cy, w, h, text, fc="white", ec=NAVY, fs=BOX_FS, lw=0.6, ls="-",
        bold=False, r=1.4):
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle=f"round,pad=0,rounding_size={r}",
        facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, zorder=3,
            linespacing=1.3, color=INK,
            fontweight="bold" if bold else "normal")


def arrow(x0, y0, x1, y1, color=NAVY, lw=0.6, ls="-"):
    ax.add_patch(FancyArrowPatch(
        (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=4.5,
        linewidth=lw, color=color, linestyle=ls, zorder=1,
        shrinkA=0, shrinkB=0))


def line(x0, y0, x1, y1, color=NAVY, lw=0.6):
    ax.plot([x0, x1], [y0, y1], color=color, lw=lw, zorder=1)


def split(y_from, y_to, cx=LCX, xl=None, xr=None):
    xl = xl if xl is not None else LX
    xr = xr if xr is not None else LRX
    mid = (y_from + y_to) / 2
    line(cx, y_from, cx, mid)
    line(xl, mid, xr, mid)
    arrow(xl, mid, xl, y_to)
    arrow(xr, mid, xr, y_to)


def merge(y_from, y_to, cx=LCX, xl=None, xr=None):
    xl = xl if xl is not None else LX
    xr = xr if xr is not None else LRX
    mid = (y_from + y_to) / 2
    line(xl, y_from, xl, mid)
    line(xr, y_from, xr, mid)
    line(xl, mid, xr, mid)
    arrow(cx, mid, cx, y_to)


# ============================================================ column headers
ax.text(LCX, H - 2.6, "OFFLINE: CORPUS CONSTRUCTION", fontsize=LBL_FS,
        fontweight="bold", ha="center", va="center", color=NAVY)
ax.text(RCX, H - 2.6, "ONLINE: QUERY", fontsize=LBL_FS, fontweight="bold",
        ha="center", va="center", color=NAVY)
line(1.5, H - 6.0, 48.0, H - 6.0, color=NAVY, lw=0.8)
line(52.0, H - 6.0, 98.5, H - 6.0, color=NAVY, lw=0.8)
ax.plot([50.0, 50.0], [3.0, H - 8.5], color="#D1D5DB", lw=0.5,
        linestyle=(0, (2, 2)), zorder=0)

# =============================================================== OFFLINE path
y = H - 12.0
box(LCX, y, COL_W_, 7.0, "Five hardware datasheet PDFs\n(1,505 pages)",
    fc=GREY_FILL)

arrow(LCX, y - 3.5, LCX, y - 8.0)
y -= 12.0
box(LCX, y, COL_W_, 7.0, "MinerU 2.5 layout-aware\nparsing (pipeline backend)")

split(y - 3.5, y - 11.5)
y -= 18.5
box(LX, y, HALF_W, 14.0,
    "Text blocks\n(10,735)\npage-grouped\nchunking\n1,298 chunks",
    fc=BLUE_FILL, ec=BLUE)
box(LRX, y, HALF_W, 14.0,
    "Figure / table\ncrops (2,393)\nGPT-5.6 Luna\ndense factual\ncaptioning",
    fc=AMBER_FILL, ec=AMBER)

merge(y - 7.0, y - 13.5)
y -= 18.5
box(LCX, y, COL_W_, 7.0, "text-embedding-3-large\n3072-d, L2 normalized")

split(y - 3.5, y - 12.0)
ax.text(LX - 12.2, y - 8.0, "visual\nvectors\nexcluded", fontsize=NOTE_FS,
        ha="left", va="center", style="italic", linespacing=1.2, color=GREY)
y -= 17.0
box(LX, y, HALF_W, 10.0, "Text-only\nindex\n1,298 vectors",
    ls=(0, (2.2, 1.6)), ec=GREY)
box(LRX, y, HALF_W, 10.0, "M-RAG index\n3,691 vectors", bold=True, lw=0.9)
ax.text(LCX, y - 8.0, "FAISS IndexFlatIP, exact cosine search",
        fontsize=NOTE_FS, ha="center", va="center", style="italic",
        color=GREY)

index_y = y

# ================================================================ ONLINE path
y = H - 12.0
box(RCX, y, COL_W_, 7.0, "Natural-language query", fc=GREY_FILL)

arrow(RCX, y - 3.5, RCX, y - 8.0)
y -= 12.0
box(RCX, y, COL_W_, 7.0, "text-embedding-3-large\n(the same encoder)")

arrow(RCX, y - 3.5, RCX, y - 8.0)
y -= 12.5
box(RCX, y, COL_W_, 6.0, "top-k retrieval, k = 5")
retrieval_y = y

arrow(RCX, y - 3.0, RCX, y - 8.0)
y -= 14.0
box(RCX, y, COL_W_, 11.0,
    "Retrieved segments\ntext snippets + captions\n+ original image crops")

arrow(RCX, y - 5.5, RCX, y - 10.0)
y -= 15.0
box(RCX, y, COL_W_, 7.0, "GPT-5.6 Sol: single\ngrounded generation call",
    bold=True, lw=0.9)

arrow(RCX, y - 3.5, RCX, y - 8.0)
y -= 12.5
box(RCX, y, COL_W_, 7.0, "Answer with source document\nand page citation",
    fc=BLUE_FILL, ec=BLUE)

# the index feeds the retrieval step
line(LRX + HALF_W / 2, index_y, 50.0, index_y, color=NAVY, lw=0.6)
line(50.0, index_y, 50.0, retrieval_y, color=NAVY, lw=0.6)
arrow(50.0, retrieval_y, RCX - COL_W_ / 2, retrieval_y)

print(f"canvas bottom margin: {y - 3.5:.1f}")
fig.savefig(OUT, dpi=600, facecolor="white", bbox_inches="tight",
            pad_inches=0.015)
print(f"wrote {OUT} ({FIG_W:.2f} x {FIG_H:.2f} in) -> renders "
      f"{FIG_H * 3.24 / FIG_W:.2f} in tall at 3.24 in wide")
