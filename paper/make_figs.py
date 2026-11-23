"""Build Figs. 2, 3 and 6 of the M-RAG IEEE paper from real pipeline artifacts.

Every figure here is composed from files the pipeline actually produced: a parsed
datasheet page with its MinerU block boxes, a real figure crop with the caption
the captioning model actually wrote, and the hand-graded eval CSV. Nothing is
mocked up. Fig. 5 (architecture) comes from make_fig.py, and Figs. 1 and 4
are schematic illustrations composited by compose_generated.py.

Run from the repo root:  .venv/Scripts/python.exe paper/make_figs.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymupdf
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
DPI = 600
COL_W = 3.30  # single IEEE column, matches the width build_paper.py places at

NAVY = "#1F3864"
BLUE = "#2563EB"
BLUE_FILL = "#DBEAFE"
AMBER = "#B45309"
AMBER_FILL = "#FDE8C8"
GREY = "#6B7280"
GREY_FILL = "#F1F3F5"
INK = "#111827"

plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["Times New Roman", "DejaVu Serif"]


def _rounded(ax, x, y, w, h, fc, ec, lw=0.7, ls="-", r=0.012, z=2):
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={r}",
        facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, zorder=z,
    )
    ax.add_patch(p)
    return p


def _arrow(ax, xy0, xy1, color=NAVY, lw=0.8, ls="-", z=4, rad=0.0):
    ax.add_patch(FancyArrowPatch(
        xy0, xy1, arrowstyle="-|>", mutation_scale=6, linewidth=lw,
        color=color, linestyle=ls, zorder=z, shrinkA=0, shrinkB=0,
        connectionstyle=f"arc3,rad={rad}",
    ))


# --------------------------------------------------------------------- Fig. 2
def fig2_page_regions():
    """A real parsed page: what each index can and cannot reach."""
    pdf = ROOT / "data/parsed/hardware/lm317/mineru/lm317/auto/lm317_origin.pdf"
    mid = json.loads(
        (ROOT / "data/parsed/hardware/lm317/mineru/lm317/auto/lm317_middle.json")
        .read_text(encoding="utf-8"))
    page_info = [p for p in mid["pdf_info"] if p["page_idx"] == 5][0]
    blocks = page_info["para_blocks"]

    clip = pymupdf.Rect(44, 62, 566, 500)          # the specification region
    doc = pymupdf.open(pdf)
    pix = doc[5].get_pixmap(dpi=400, clip=clip)
    png = OUT / "figures" / "raw" / "_lm317_p6_clip.png"
    pix.save(png)
    img = plt.imread(png)

    fig = plt.figure(figsize=(COL_W, COL_W * 0.62))
    fig.patch.set_facecolor("white")

    # ---- left: the page with its parsed regions marked
    ax = fig.add_axes([0.015, 0.055, 0.545, 0.815])
    ax.imshow(img, extent=(clip.x0, clip.x1, clip.y1, clip.y0), aspect="auto",
              interpolation="lanczos", zorder=1)
    ax.set_xlim(clip.x0, clip.x1)
    ax.set_ylim(clip.y1, clip.y0)
    for b in blocks:
        x0, y0, x1, y1 = b["bbox"]
        visual = b["type"] in ("table", "image")
        ax.add_patch(Rectangle(
            (x0, y0), x1 - x0, y1 - y0,
            facecolor=(AMBER_FILL if visual else "none"),
            edgecolor=(AMBER if visual else BLUE),
            linewidth=(0.65 if visual else 0.45),
            linestyle=("-" if visual else (0, (2.2, 1.4))),
            alpha=(0.55 if visual else 1.0), zorder=3))
    for s in ax.spines.values():
        s.set_edgecolor(GREY)
        s.set_linewidth(0.6)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("LM317 datasheet, p. 6 (parsed)", fontsize=5.6, color=INK,
                 pad=2.5)

    # ---- right: what each index holds
    bx = fig.add_axes([0.585, 0.055, 0.405, 0.815])
    bx.set_xlim(0, 1)
    bx.set_ylim(0, 1)
    bx.axis("off")

    bx.text(0.5, 0.985, "“What is the maximum\noutput current?”",
            fontsize=5.4, ha="center", va="top", style="italic", color=INK,
            linespacing=1.25)

    def panel(y, h, title, n_text, n_vis, ok):
        _rounded(bx, 0.0, y, 1.0, h, "white", GREY, lw=0.6, r=0.03)
        bx.text(0.05, y + h - 0.035, title, fontsize=5.4, va="top",
                fontweight="bold", color=INK)
        cy = y + h - 0.115
        for i in range(n_text):
            _rounded(bx, 0.06, cy - i * 0.052, 0.62, 0.032, BLUE_FILL, BLUE,
                     lw=0.4, r=0.008)
        for i in range(n_vis):
            _rounded(bx, 0.70, cy - i * 0.052, 0.24, 0.032, AMBER_FILL, AMBER,
                     lw=0.4, r=0.008)
        mark, col, txt = (("✓", BLUE, "answer reachable") if ok
                          else ("✗", AMBER, "answer not indexed"))
        bx.text(0.06, y + 0.035, mark, fontsize=7.2, color=col, va="center",
                fontweight="bold", family="DejaVu Sans")
        bx.text(0.15, y + 0.038, txt, fontsize=5.2, color=INK, va="center")

    panel(0.475, 0.335, "Text-only index", 3, 0, False)
    panel(0.075, 0.335, "M-RAG index", 3, 3, True)

    _arrow(bx, (0.5, 0.465), (0.5, 0.425), color=GREY, lw=0.6)

    handles = [
        Line2D([], [], color=BLUE, lw=0.8, ls=(0, (2.2, 1.4)),
               label="text block"),
        Line2D([], [], color=AMBER, lw=2.4, alpha=0.55,
               label="table / figure region"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False,
               fontsize=5.2, bbox_to_anchor=(0.5, -0.012),
               handlelength=1.5, columnspacing=1.6, handletextpad=0.5)

    p = OUT / "fig2_page_regions.png"
    fig.savefig(p, dpi=DPI, facecolor="white", bbox_inches="tight",
                pad_inches=0.015)
    plt.close(fig)
    png.unlink(missing_ok=True)
    print("wrote", p)


# --------------------------------------------------------------------- Fig. 3
CAPTION_LINES = [
    ("Figure 1-1. Pinout ATmega48A/88A/168A/328/P", "head"),
    ("Top-view pinouts for 32 TQFP, 28 SPDIP, 28", "body"),
    ("VQFN and 32 VQFN packages. Pin labels give", "body"),
    ("port names and alternate functions.", "body"),
    ("32 TQFP Top View", "head"),
    ("  Pin 1: PD3 (PCINT19/OC2B/INT1)", "body"),
    ("  Pin 2: PD4 (PCINT20/XCK/T0)", "body"),
    ("  ...", "body"),
    ("  Pin 31: PD1 (TXD/PCINT17)", "body"),
    ("28 SPDIP", "head"),
    ("  Pin 1: PC6 (PCINT14/RESET)", "body"),
    ("  Pin 2: PD0 (PCINT16/RXD)", "body"),
    ("  Pin 3: PD1 (PCINT17/TXD)", "hit"),
    ("  Pin 4: PD2 (PCINT18/INT0)", "body"),
    ("  ...", "body"),
]


def fig3_captioning():
    """A real crop beside the dense caption the model actually produced."""
    segs = json.loads(
        (ROOT / "data/parsed/hardware/atmega328p/segments.json")
        .read_text(encoding="utf-8"))
    seg = [s for s in segs
           if s["segment_id"] == "atmega328p-p0012-figure-00001"][0]
    crop = plt.imread(ROOT / seg["image_path"])

    fig = plt.figure(figsize=(COL_W, COL_W * 0.545))
    fig.patch.set_facecolor("white")

    ax = fig.add_axes([0.005, 0.10, 0.320, 0.80])
    ax.imshow(crop, interpolation="lanczos")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_edgecolor(GREY)
        s.set_linewidth(0.6)
    ax.set_title("figure crop, p. 12", fontsize=5.2, color=GREY, pad=2)

    bx = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    bx.set_xlim(0, 1)
    bx.set_ylim(0, 1)
    bx.axis("off")

    # the label sits in the gap between the crop and the caption panel, above
    # the arrow; keep it clear of both edges (crop ends 0.325, panel starts 0.47)
    _arrow(bx, (0.345, 0.50), (0.462, 0.50), color=NAVY, lw=0.9)
    bx.text(0.4035, 0.545, "dense factual\ncaptioning", fontsize=4.2,
            ha="center", va="bottom", color=NAVY, linespacing=1.2)

    _rounded(bx, 0.470, 0.075, 0.527, 0.845, "#FCFCFD", GREY, lw=0.6, r=0.02)
    y = 0.878
    for text, kind in CAPTION_LINES:
        if kind == "hit":
            _rounded(bx, 0.481, y - 0.0115, 0.505, 0.047, "#FEF08A", "#CA8A04",
                     lw=0.45, r=0.006, z=3)
        bx.text(0.489, y, text, fontsize=4.25, va="center", zorder=4,
                family="monospace", color=INK,
                fontweight=("bold" if kind in ("head", "hit") else "normal"))
        y -= 0.0555
    bx.text(0.734, 0.048, "caption as stored: 4,361 characters",
            fontsize=4.6, ha="center", va="center", style="italic", color=GREY)

    p = OUT / "fig3_captioning.png"
    fig.savefig(p, dpi=DPI, facecolor="white", bbox_inches="tight",
                pad_inches=0.015)
    plt.close(fig)
    print("wrote", p)


# --------------------------------------------------------------------- Fig. 6


def fig6_results():
    """Answer accuracy by question split, read out of the graded CSV.

    Accuracy only: in every cell of this experiment the retrieval hit rate is
    identical to it, so plotting both would duplicate the same six bars. The
    grade distribution this figure once carried is stated in the prose of
    Section VII-B instead, which costs less column height.
    """
    rows = list(csv.DictReader(
        (ROOT / "eval/results.csv").open(encoding="utf-8")))

    def sel(mode, visual):
        return [r for r in rows
                if r["mode"] == mode
                and (visual is None
                     or (r["requires_visual"].strip().lower() == "true")
                     == visual)]

    def accuracy(mode, visual):
        s = sel(mode, visual)
        n = sum(1 for r in s if r["answer_score"].strip().lower() == "correct")
        return 100.0 * n / len(s)

    fig, top = plt.subplots(figsize=(COL_W, COL_W * 0.50))
    fig.patch.set_facecolor("white")

    groups = [("Visual-required\n(n = 13)", True),
              ("Prose control\n(n = 5)", False),
              ("All questions\n(n = 18)", None)]
    xs = list(range(len(groups)))
    w = 0.34
    for off, mode, col, ec in [(-w / 2, "mrag", BLUE, BLUE),
                               (w / 2, "text_only", "#E5E7EB", GREY)]:
        vals = [accuracy(mode, v) for _, v in groups]
        bars = top.bar([x + off for x in xs], vals, w, color=col,
                       edgecolor=ec, linewidth=0.5, zorder=3)
        for b, v in zip(bars, vals):
            top.text(b.get_x() + b.get_width() / 2, b.get_height() + 2.0,
                     f"{v:.1f}%", ha="center", va="bottom", fontsize=5.0,
                     color=INK, zorder=4)
    top.set_xticks(xs)
    top.set_xticklabels([g[0] for g in groups], fontsize=5.2)
    top.set_ylim(0, 100)
    top.set_yticks([0, 25, 50, 75, 100])
    top.set_yticklabels(["0", "25", "50", "75", "100"], fontsize=5.2)
    top.set_ylabel("percent", fontsize=5.4, labelpad=1.5)
    top.grid(axis="y", color="#E5E7EB", linewidth=0.4, zorder=0)
    top.set_axisbelow(True)
    top.legend(handles=[
        Rectangle((0, 0), 1, 1, facecolor=BLUE, edgecolor=BLUE, label="M-RAG"),
        Rectangle((0, 0), 1, 1, facecolor="#E5E7EB", edgecolor=GREY,
                  label="Text-only baseline")],
        loc="upper right", frameon=False, fontsize=5.0, handlelength=1.0,
        handleheight=0.8, handletextpad=0.4, borderaxespad=0.2,
        labelspacing=0.3)
    for side in ("top", "right"):
        top.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        top.spines[side].set_edgecolor(GREY)
        top.spines[side].set_linewidth(0.5)
    top.tick_params(length=1.6, width=0.4, pad=1.4)
    fig.subplots_adjust(left=0.115, right=0.99, top=0.97, bottom=0.20)

    p = OUT / "fig6_results.png"
    fig.savefig(p, dpi=DPI, facecolor="white", bbox_inches="tight",
                pad_inches=0.015)
    plt.close(fig)
    print("wrote", p)


if __name__ == "__main__":
    fig2_page_regions()
    fig3_captioning()
    fig6_results()
