"""Extend the M-RAG IEEE paper with the mandatory sections III-VIII.

Reads the original .docx, edits in place in memory, writes to a new file so the
source is never touched.
"""

import copy
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH as ALIGN
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt

SRC = Path(r"C:\Users\abhii\Downloads"
           r"\23eg105p02_cse_Bhavya Sri_miniproject_15-07-2026-Updated.docx")
DST = Path(r"C:\Users\abhii\Downloads"
           r"\M-RAG_Paper_Complete_IEEE.docx")
# Figures live beside this script. Figs. 2, 3 and 6 are built from real
# pipeline artifacts by make_figs.py, Fig. 5 by make_fig.py; Figs. 1 and 4 are
# schematic illustrations composited by compose_generated.py.
_FIGS = Path(__file__).resolve().parent
FIG1 = _FIGS / "fig1_coverage.png"        # I,    the coverage problem
FIG2 = _FIGS / "fig2_page_regions.png"    # III-A, a real parsed page
FIG3 = _FIGS / "fig3_captioning.png"      # IV-B, a real crop and its caption
FIG4 = _FIGS / "fig4_deferred.png"        # IV-C, caption retrieves, image generates
FIG5 = _FIGS / "fig5_architecture.png"    # V,    the pipeline
FIG6 = _FIGS / "fig6_results.png"         # VII-A, the graded results

for _f in (FIG1, FIG2, FIG3, FIG4, FIG5, FIG6):
    if not _f.exists():
        raise SystemExit(f"missing figure: {_f}\nRun make_fig.py, make_figs.py "
                         f"and compose_generated.py first.")

BODY = "Body Text Indent"
doc = docx.Document(str(SRC))

# The source uses 30 blank paragraphs as ad-hoc vertical spacing, including one
# between every pair of references. With six figures competing for column space
# they cost roughly a quarter of a page. Collect them now and drop them at the
# very end, after the anchors that rely on them have been used; the title block
# keeps its own spacing. Blank spacers this script creates via Anchor.gap() are
# deliberate and are never in this list.
_SOURCE_BLANKS = [p for p in doc.paragraphs[3:] if not p.text.strip()]


# --------------------------------------------------------------- helpers
def set_text(p, text):
    """Replace a paragraph's text, keeping the first run's formatting."""
    for r in list(p.runs)[1:]:
        r._r.getparent().remove(r._r)
    if p.runs:
        p.runs[0].text = text
    else:
        p.add_run(text)
    return p


def find_para(fragment):
    for p in doc.paragraphs:
        if fragment in p.text:
            return p
    raise LookupError(f"paragraph not found: {fragment!r}")


class Anchor:
    """Inserts content immediately before a fixed anchor paragraph."""

    def __init__(self, para):
        self.a = para

    def head(self, text):
        p = self.a.insert_paragraph_before(text, style="Heading 1")
        return p

    def sub(self, text):
        p = self.a.insert_paragraph_before(style=BODY)
        r = p.add_run(text)
        r.italic = True
        return p

    def body(self, text):
        return self.a.insert_paragraph_before(text, style=BODY)

    def caption(self, text, size=8, bold=False, space_before=6, space_after=2,
                keep=True):
        p = self.a.insert_paragraph_before(style="Normal")
        p.alignment = ALIGN.CENTER
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.bold = bold
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.keep_with_next = keep
        return p

    def gap(self, size=4):
        p = self.a.insert_paragraph_before(style="Normal")
        p.paragraph_format.space_after = Pt(size)
        return p

    def picture(self, path, width_in):
        p = self.a.insert_paragraph_before(style="Normal")
        p.alignment = ALIGN.CENTER
        p.add_run().add_picture(str(path), width=Inches(width_in))
        p.paragraph_format.keep_with_next = True
        return p

    def table(self, header, rows, widths, header_size=7.5, body_size=7.0):
        t = doc.add_table(rows=len(rows) + 1, cols=len(header))
        _borders(t)
        _grid(t, widths)
        for j, cell_text in enumerate(header):
            _cell(t.rows[0].cells[j], cell_text, header_size,
                  bold=True, center=True)
        for i, row in enumerate(rows, start=1):
            for j, cell_text in enumerate(row):
                _cell(t.rows[i].cells[j], cell_text, body_size,
                      center=(j > 0))
        _no_row_split(t)
        self.a._p.addprevious(t._tbl)
        return t

    def algorithm(self, title, lines):
        t = doc.add_table(rows=1, cols=1)
        _borders(t)
        _grid(t, [4670])
        cell = t.rows[0].cells[0]
        cell.paragraphs[0]._p.getparent().remove(cell.paragraphs[0]._p)
        first = True
        for line, bold in lines:
            p = cell.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(3 if first else 0)
            p.paragraph_format.left_indent = Pt(2)
            r = p.add_run(line)
            r.font.size = Pt(7.0)
            r.bold = bold
            first = False
        _no_row_split(t)
        self.a._p.addprevious(t._tbl)
        return t


def _no_row_split(table):
    """Stop a row (and so a one-row algorithm box) breaking across columns."""
    for row in table.rows:
        trPr = row._tr.get_or_add_trPr()
        if trPr.find(qn("w:cantSplit")) is None:
            trPr.append(OxmlElement("w:cantSplit"))


def _borders(table):
    tblPr = table._tbl.tblPr
    for existing in tblPr.findall(qn("w:tblBorders")):
        tblPr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "4")
        e.set(qn("w:color"), "000000")
        borders.append(e)
    tblPr.append(borders)


def _grid(table, widths):
    table.autofit = False
    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        table._tbl.remove(grid)
    grid = OxmlElement("w:tblGrid")
    for w in widths:
        gc = OxmlElement("w:gridCol")
        gc.set(qn("w:w"), str(w))
        grid.append(gc)
    table._tbl.insert(1, grid)
    tblW = table._tbl.tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        table._tbl.tblPr.append(tblW)
    tblW.set(qn("w:w"), str(sum(widths)))
    tblW.set(qn("w:type"), "dxa")
    for row in table.rows:
        for cell, w in zip(row.cells, widths):
            cell.width = Pt(w / 20.0)


def _cell(cell, text, size, bold=False, center=False):
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    if center:
        p.alignment = ALIGN.CENTER
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold


# ================================================================ ABSTRACT
set_text(
    find_para("Technical documents, such as research papers"),
    "Abstract: Technical documents such as manuals and component specification "
    "sheets carry much of their information in diagrams and tables the "
    "surrounding prose never restates, and standard retrieval systems index "
    "only the written words, so an answer that lives in a figure is simply "
    "unavailable. This paper presents and evaluates a Multimodal "
    "Retrieval-Augmented Generation (M-RAG) pipeline that closes the gap. "
    "Pages are parsed into text blocks and cropped visual regions, a "
    "vision-capable large language model transcribes each region into a dense "
    "factual caption carrying its labels, symbols and numeric values, and one "
    "text encoder embeds captions and prose chunks into a single space indexed "
    "with Facebook AI Similarity Search (FAISS). At query time the top-ranked "
    "segments are retrieved regardless of modality, and each retrieved visual "
    "contributes its original crop, not its caption alone, to one grounded "
    "generation call. Built over five public hardware datasheets spanning "
    "1,505 pages, the pipeline yielded 13,128 parsed segments and 3,691 "
    "indexed vectors, and was compared against a text-only baseline produced "
    "by the identical code with visual vectors excluded. Over 18 hand-graded "
    "questions M-RAG answered 66.7% correctly against 22.2% for the baseline. "
    "On the 13 questions whose ground truth exists only in a figure or table "
    "it reached 61.5% retrieval hit rate and 61.5% accuracy against 0.0% on "
    "both, and the two tied at 80.0% on five prose controls. Every M-RAG "
    "failure was a retrieval failure: on all 12 questions where correct "
    "evidence was retrieved, the answer was correct.")

set_text(
    find_para("Index Terms"),
    "Index Terms \u2014 Document understanding, multimodal retrieval, "
    "retrieval-augmented generation with large language models, vector "
    "embeddings, Facebook AI Similarity Search (FAISS), document parsing, "
    "hardware datasheets.")

# ============================================================ SECTION I / II
set_text(find_para("Introduction"), "I. Introduction")
set_text(find_para("Literature survey"), "II. Related Work")

# Introduction: nine paragraphs condensed to six. Three are absorbed into the
# survivors; one (the second "this is a text problem" paragraph) restated its
# predecessor almost verbatim. Section II loses the standalone LayoutLM
# paragraph, which Table I already tabulates in full.
for _frag in ("In standard document retrieval systems this is a text problem",
              "As organizations shift from manual lookup",
              "There is a large literature that has addressed this question",
              "Before any retrieval can occur"):
    _dead = find_para(_frag)
    _dead._p.getparent().remove(_dead._p)

set_text(
    find_para("Technical documents can be published in a wide variety"),
    "Technical documents take many forms: research papers, product manuals, "
    "engineering specifications, regulatory reports. None of them is "
    "general-purpose prose. Each mixes written content with visual material, "
    "and the two channels are not redundant. Diagrams, schematics, tolerance "
    "tables and annotated charts carry measurements, spatial relationships and "
    "structured data that the surrounding paragraphs do not repeat. Pin "
    "assignments and signal paths in a hardware manual appear in the wiring "
    "layout and nowhere else.")

set_text(
    find_para("For instance, technical documents frequently feature diagrams"),
    "Standard retrieval systems treat a document as text. They extract and "
    "index the written words, then answer queries from that index. When the "
    "answer sits in a table, such a system returns nothing useful or assembles "
    "a partial answer out of whatever prose happened to mention the figure in "
    "passing. Visual content is structurally inaccessible to it. The cost is "
    "mundane and recurring: engineers re-derive information a diagram already "
    "states, and knowledge encoded in figures stays unsearchable even when the "
    "document holding it sits in the corpus.")

_p_rag = set_text(
    find_para("Retrieval-Augmented Generation (RAG) offers an established"),
    "Retrieval-Augmented Generation (RAG) already solves the text half of the "
    "problem. Instead of answering from training memory, the model receives "
    "passages retrieved from an external corpus at query time and answers from "
    "that context [2]. Retrieve-then-generate is now the standard architecture "
    "for question answering over private or frequently updated collections.")

# Fig. 1 follows the paragraph that states the coverage problem, so the reader
# meets the failure mode before the formal treatment in Section III.
_a1 = Anchor(_p_rag)
_a1.picture(FIG1, 3.24)
_a1.caption("Fig. 1.    Why a text-only index answers incompletely. Parsing "
            "separates a technical document into text blocks, tables and "
            "figures, but only the text blocks are indexed. A question whose "
            "answer exists solely in a table or a diagram is then answered "
            "from prose that never states it.", size=7.5, keep=False)

set_text(
    find_para("Extending RAG to visual content is not a trivial task"),
    "Extending RAG to visual content is harder. A vector produced from a "
    "sentence and one produced from an image do not share a space, so "
    "cross-modal retrieval from a single index has to close that gap first. "
    "Contrastive pretraining over image-caption collections [5], adapter-based "
    "bridging of a frozen vision encoder to a language model [6] and joint "
    "encoding of image regions with text tokens in one transformer [10] all "
    "establish the alignment principle on which cross-modal retrieval rests.")

set_text(
    find_para("A raw document must be parsed into retrievable segments"),
    "Retrieval also presupposes parsing. Technical content is spatially "
    "organized, and a plain text stream discards structure that carries "
    "meaning; the layout-aware and OCR-free parsers reviewed in Section II "
    "[3], [7], [8], [9] recover it. The indexing layer here is Facebook AI "
    "Similarity Search (FAISS) [4], fast enough for dense nearest-neighbour "
    "search over millions of vectors.")

# Closing paragraph of the Introduction: replace the multi-domain promise.
set_text(
    find_para("The closest prior system is a multimodal RAG framework"),
    "The closest prior system is a multimodal RAG framework for the "
    "architecture domain that retrieves from visual and textual parts alike "
    "and passes the fused context to a multimodal language model [1]. It is "
    "the only reviewed system combining multimodal embedding, retrieval and "
    "generation in one pipeline, and its validation stops at architectural "
    "drawings and specifications. This project generalizes it to a different "
    "class of visually rich technical documents. Text and visual segments are "
    "embedded into a common vector space and indexed with FAISS, so a query "
    "retrieves passages and figures together whichever modality holds the "
    "answer. The pipeline is evaluated end to end on hardware and electronics "
    "datasheets against a text-only baseline sharing its entire code path.")

# Contributions paragraph goes immediately before the Section II heading.
_sec2 = find_para("II. Related Work")
_a2 = Anchor(_sec2)
_a2.body(
    "This paper contributes an M-RAG architecture in which visual regions "
    "become retrievable through dense factual captioning, so one text encoder "
    "suffices and no jointly trained image-text model is required; a "
    "deferred-image generation step in which captions act only as retrieval "
    "surrogates while the original crop reaches the generator, keeping caption "
    "compression off the accuracy ceiling; a modality-controlled baseline, the "
    "same index with visual vectors removed, so any measured difference is "
    "attributable to modality coverage alone; and a hand-graded evaluation "
    "recording retrieval success and answer correctness as independent fields, "
    "which tells retrieval failures apart from generation failures.")

# Related Work: Table I already carries method, contribution and gap for every
# surveyed system, so the prose keeps only what the table cannot say.
set_text(
    find_para("The retrieve-then-generate approach was formalized"),
    "Table I compares the surveyed systems; the discussion below groups them "
    "by the layer each one addresses. Lewis et al. [2] paired a dense "
    "retriever with a sequence-to-sequence generator so that outputs could be "
    "grounded in passages fetched at query time, establishing the "
    "retrieve-then-generate pattern. Scaling it to large collections demands "
    "fast similarity search, which Johnson et al. [4] supplied with "
    "GPU-accelerated approximate nearest-neighbour search.")

set_text(
    find_para("Applying RAG across text and images requires"),
    "Applying RAG across modalities requires text and images to share a vector "
    "space. Radford et al. trained on 400 million image-caption pairs with a "
    "contrastive objective that pulls matched pairs together and pushes "
    "mismatched ones apart, transferring to zero-shot visual tasks without "
    "fine-tuning [5]. BLIP-2 instead bridges a frozen vision encoder to a "
    "frozen language model through a lightweight Q-Former adapter [6], and "
    "Visual BERT encodes image regions and text tokens together with shared "
    "self-attention [10].")

set_text(
    find_para("Huang et al. extended LayoutLMv3"),
    "Parsing sits beneath retrieval: a technical page is spatially organized, "
    "and plain text extraction throws that structure away. Xu et al. added 2D "
    "bounding-box coordinates for every token to pretraining, showing that "
    "position on a page carries information of its own [8]. LayoutLMv3 "
    "unified text, layout and image patches under one masking framework [7], "
    "Donut removed the OCR stage and decoded structured output straight from "
    "the page image [9], and MinerU2.5 separated coarse layout detection from "
    "per-region recognition to keep high-resolution pages efficient [3].")

set_text(
    find_para("The most similar system to the proposal"),
    "Meng and Tong built the system closest to this proposal [1]. It extracts "
    "text and visual elements, embeds both into a common space, retrieves by "
    "semantic search and hands the combined context to a multimodal language "
    "model, the first to join all three in one document question-answering "
    "pipeline. Its evaluation covered architectural drawings and "
    "specifications only.")

set_text(
    find_para("The analyzed work is divided into three functional groups"),
    "The surveyed work falls into three functional groups: retrieval and "
    "indexing in [2] and [4], alignment in [5], [6] and [10], and parsing in "
    "[3], [7], [8] and [9]. The alignment and parsing models neither retrieve "
    "nor answer; the retrieval systems never touch visual content.")

# Summary-of-survey closing paragraph: remove the multi-domain claim.
set_text(
    find_para("The only work that combines all three layers"),
    "Only Meng and Tong [1] combine all three layers in a working system, and "
    "their evaluation was confined to architecture, so behaviour on other "
    "classes of visually rich technical document is untested. This work "
    "generalizes it to hardware and electronics datasheets, a class with "
    "different visual conventions: dense electrical-characteristics tables, "
    "timing specifications and package pinout diagrams in place of "
    "architectural drawings. Simultaneous validation across two or more "
    "domains remains open and is future work in Section VIII.")

# The source left a bare "Comparative table" placeholder above the table; it
# renders as stray body text and is replaced by the real caption below.
_ph = find_para("Comparative table")
_ph._p.getparent().remove(_ph._p)

# Caption the existing comparative table as Table I, directly above the table.
_p = doc.add_paragraph(style="Normal")
_p.alignment = ALIGN.CENTER
_r = _p.add_run("TABLE I.    COMPARATIVE ANALYSIS OF SURVEYED WORK")
_r.font.size = Pt(8)
_p.paragraph_format.space_after = Pt(2)
doc.tables[1]._tbl.addprevious(_p._p)

print("edits to existing content: done")

# =============================================== NEW SECTIONS III - VIII
_ref_idx = [i for i, p in enumerate(doc.paragraphs)
            if p.text.strip() == "References"][0]
# step back to the empty Heading 1 that precedes "References"
A = Anchor(doc.paragraphs[_ref_idx - 1])

# ------------------------------------------------------------- SECTION III
A.head("III. Problem Statement and Motivation")

A.sub("A. Problem statement")
A.body(
    "Let D be a corpus of technical documents. Parsing decomposes each "
    "document d into segments S(d) = T(d) \u222a V(d), where T(d) holds the "
    "text blocks and V(d) the visual regions, each a cropped image of a figure "
    "or table with its page coordinates. A retrieval system is an embedding "
    "function e(\u00b7) plus an index I over a set U of retrievable units; "
    "given a query q it returns the k units of U closest to e(q). A text-only "
    "system indexes Utext = chunk(T); a multimodal system indexes Umm = "
    "chunk(T) \u222a {\u03c6(v) : v \u2208 V}, where \u03c6 maps a visual "
    "region to a unit e(\u00b7) can embed. The whole difference between the "
    "two is the set {\u03c6(v)}.")
A.body(
    "Call a question q visual-required when every segment carrying evidence "
    "sufficient for its ground-truth answer lies in V and no text block "
    "restates it. Utext then holds no unit containing the answer, so for every "
    "k the top-k set cannot contain sufficient evidence. Coverage is a "
    "property of the index, not a tuning knob on the retriever: increasing k, "
    "reranking candidates or improving the prompt recovers nothing that was "
    "never indexed. Fig. 2 shows the property on one parsed page. Constructing "
    "\u03c6 therefore carries three requirements. It must yield units the same "
    "encoder e embeds, so visual and textual scores are directly comparable. "
    "It must preserve exact identifiers, numeric values, units and test "
    "conditions. And its information loss must not bound the accuracy of the "
    "answer.")

A.picture(FIG2, 3.24)
A.caption("Fig. 2.    The coverage property on a real page. Page 6 of the "
          "LM317 datasheet as the parser segments it; dashed outlines are text "
          "blocks and shaded regions are tables. The maximum output current is "
          "stated only inside a table, so it enters the M-RAG index and is "
          "absent from the text-only index at every value of k.",
          size=7.5, keep=False)

A.sub("B. Motivation")
A.body(
    "Hardware datasheets stress this problem in three ways. Visual content "
    "carries a large share of the answers: of the 13,128 segments parsed from "
    "the corpus of Section VI, 2,393 or 18.2% are figures or tables, holding "
    "the pin assignments, absolute-maximum ratings, thermal resistances and "
    "timing values that most practical queries ask about.")
A.body(
    "The answers are also exact. A semantically related passage rarely "
    "satisfies a datasheet question: \u201cpin 30\u201d and \u201cpin 3\u201d "
    "sit close together in any embedding space and are worlds apart in "
    "practice. A contrastive image-text encoder of the kind in [5] does not "
    "suffice on its own, since such encoders align an image with a description "
    "of what it depicts and do not preserve the numeric contents of a "
    "forty-row electrical-characteristics table.")
A.body(
    "The comparison must also be fair. A claim that multimodal retrieval helps "
    "means something only against a baseline differing in exactly one respect; "
    "a separately built text-only system confounds modality coverage with "
    "incidental differences in chunking, embedding and retrieval. How the "
    "system fails matters as much: an aggregate accuracy figure cannot "
    "separate a system that retrieves the correct table and misreads it from "
    "one that never retrieves it, and the two have different remedies. The "
    "evaluation records retrieval success and answer correctness as "
    "independent quantities.")

A.sub("C. Hypotheses")
A.body(
    "H1. Indexing visual regions alongside text raises both the retrieval hit "
    "rate and the answer accuracy on visual-required questions, relative to a "
    "text-only baseline that shares the same code path.")
A.body(
    "H2. Doing so does not degrade either quantity on control questions whose "
    "answers appear in prose.")

# -------------------------------------------------------------- SECTION IV
A.head("IV. Proposed System")
A.body(
    "The system follows the retrieve-then-generate pattern formalized in [2] "
    "and its multimodal extension in [1], adding three design commitments: "
    "caption-mediated bridging of the modality gap, deferred attachment of the "
    "original image, and a modality-controlled baseline. Fig. 5 shows the "
    "complete pipeline.")

A.sub("A. Layout-aware parsing")
A.body(
    "Documents are parsed with MinerU 2.5 [3] instead of a plain text "
    "extractor, since separating coarse layout detection from per-region "
    "recognition keeps it practical on the high-resolution, densely tabulated "
    "pages typical of datasheets. Each page yields typed segments: text "
    "blocks, figures and tables. Every visual segment is emitted as a cropped "
    "image with its source document, page number and any adjacent caption "
    "text. The alternatives in Table I do not fit, producing layout-aware "
    "token representations or whole-page decodings rather than the retrievable "
    "crops Section IV-C requires.")

A.sub("B. Bridging the modality gap by dense captioning")
A.body(
    "\u03c6 is implemented as dense factual captioning. Each cropped region "
    "goes to a vision-capable large language model under a prompt that demands "
    "transcription, not description. For a pinout or package diagram the model "
    "enumerates every legible pin number with its exact label and function and "
    "states orientation markers and grouped signals. For a table it states the "
    "title, column headings, test conditions and units, then transcribes each "
    "parameter with its minimum, typical and maximum values as shown, footnote "
    "markers preserved. Anything genuinely illegible is reported as illegible "
    "and never guessed. Fig. 3 shows one crop beside the caption stored for "
    "it.")

A.picture(FIG3, 3.24)
A.caption("Fig. 3.    Dense factual captioning turns a visual region into a "
          "retrievable text surrogate. Left, the ATmega328P package pinout "
          "crop from page 12. Right, an excerpt of the caption the captioning "
          "model produced and stored for it. The highlighted line is the "
          "ground truth for one of the evaluation questions of Section VI-D.",
          size=7.5, keep=False)

A.body(
    "This departs from the alignment strategies of [5], [6] and [10], which "
    "learn a joint space where an image and its description become neighbours. "
    "That objective suits semantic image retrieval and fails here, because two "
    "electrical-characteristics tables of identical structure and different "
    "numbers are near-identical images with entirely distinct answers. "
    "Converting the region to text before embedding shifts the burden from "
    "geometric alignment to transcription, which vision models do well. "
    "One text encoder then suffices, with no paired training data and no "
    "fine-tuning; both modalities are scored by the same function, so their "
    "similarities compare directly; and each surrogate is human-readable, so a "
    "retrieval failure can be diagnosed by reading the caption that missed.")

A.sub("C. Deferred image attachment")
A.body(
    "A caption is a lossy encoding of its region, and a dense table can exceed "
    "what any caption preserves. If the caption were also the generator's only "
    "view of the region, transcription loss would cap answer accuracy. The "
    "system splits the two roles. The caption serves retrieval alone; once a "
    "visual segment enters the retrieved set, the original crop is attached to "
    "the generation request alongside the retrieved text, the caption "
    "travelling with it as an annotation. Retrieval recall then depends on "
    "caption quality and answer fidelity on the generator reading actual "
    "pixels, so the two improve independently. All retrieved segments enter a "
    "single generation call, letting the model combine evidence spread across "
    "several segments instead of the top-ranked one alone. Fig. 4 sets the two "
    "roles side by side.")

A.picture(FIG4, 3.24)
A.caption("Fig. 4.    Deferred image attachment. The caption is a retrieval "
          "surrogate and nothing more; it carries the region into the shared "
          "vector space. The original crop travels separately and unchanged to "
          "the generation call, so caption compression bounds recall without "
          "bounding answer fidelity.", size=7.5, keep=False)

A.sub("D. A modality-controlled baseline")
A.body(
    "The text-only baseline is the same system minus one component. It runs "
    "the same parsing, chunking, embedding and retrieval code and differs in "
    "exactly one respect: caption vectors are absent from its index. Its text "
    "vectors are the identical vectors used in the multimodal index, drawn "
    "from the same content-addressed cache. Any measured difference between "
    "the two configurations is attributable to the presence or absence of "
    "visual units.")

A.sub("E. Deployment-agnostic model boundary")
A.body(
    "The architecture assumes two capabilities and no more: something that "
    "embeds text, and something that captions and generates from images. All "
    "model access is confined to two functions, one mapping text to a vector "
    "and one mapping a prompt and optional images to text, each defined once "
    "and imported by every stage; no stage constructs an API client. "
    "Substituting a locally served open-weight model for the hosted "
    "deployments used here changes two function bodies and leaves the "
    "architecture untouched, so the on-premise claim is checkable in the "
    "code.")

# --------------------------------------------------------------- SECTION V
A.head("V. System Architecture and Algorithms")
A.body(
    "Fig. 5 shows the two paths. The offline path runs once per corpus and "
    "produces both indexes; the online path runs once per query.")

A.picture(FIG5, 3.24)
A.caption("Fig. 5.    Architecture of the M-RAG pipeline. The offline path "
          "parses each datasheet into text blocks and visual crops, captions "
          "every crop, and embeds both streams with one text encoder into two "
          "indexes that differ only by the exclusion of visual vectors. The "
          "online path embeds the query with the same encoder and attaches the "
          "original crops, not the captions alone, to a single generation "
          "call.", size=7.5, keep=False)

A.sub("A. Segment representation")
A.body(
    "Every indexed vector carries a metadata record giving its segment "
    "identifier, source document, page number, segment type and the exact text "
    "or caption embedded; visual records add the crop path and the captioning "
    "model. The crop path lets the online path attach original pixels at "
    "generation time, and the page number lets an answer cite its source. One "
    "metadata file serves both indexes, so a text vector means the same thing "
    "in either configuration.")

A.sub("B. Similarity computation")
A.body(
    "All vectors are L2-normalized before insertion and both indexes are exact "
    "flat inner-product indexes, so for unit vectors the inner product is the "
    "cosine similarity. An exhaustive index returns the true top-k and adds no "
    "recall loss of its own, so any retrieval miss reported in Section VII "
    "belongs to the representation and not to an approximate search. The "
    "approximate structures of [4] become necessary at much larger corpus "
    "sizes; at 3,691 vectors an exhaustive scan is cheap and removes a "
    "confounder.")

A.sub("C. Chunking")
A.body(
    "Text blocks are grouped by document and page and concatenated before "
    "chunking, so a value and the heading or row label qualifying it are not "
    "split by a block boundary. The page text is then divided into the number "
    "of chunks whose mean length comes closest to a target of roughly 400 "
    "whitespace tokens, with tokens spread evenly instead of greedily filling "
    "a fixed window and leaving a short remainder. Across the corpus this gave "
    "1,298 text chunks averaging 189 whitespace tokens, median 176.")

A.sub("D. Algorithms")
A.body(
    "Algorithm 1 builds the corpus and both indexes; Algorithm 2 answers one "
    "query. The mode argument in Algorithm 2 selects the index and with it "
    "whether visual evidence can be retrieved at all. Every other step is "
    "shared.")

A.gap(3)
A.algorithm("Algorithm 1", [
    ("Algorithm 1  Offline corpus construction", True),
    ("Input: document set D; chunk target \u03c4 = 400 tokens", False),
    ("Output: indexes Imm and Itext; metadata M", False),
    ("  1:  S \u2190 \u2205", False),
    ("  2:  for each document d \u2208 D do", False),
    ("  3:      S \u2190 S \u222a ParseLayout(d)   \u25b7 typed segments, "
     "page, crop", False),
    ("  4:  for each visual segment v \u2208 S do", False),
    ("  5:      if caption of v not in cache then", False),
    ("  6:          c(v) \u2190 Generate(CaptionPrompt(v), images = crop(v))",
     False),
    ("  7:          persist c(v) to cache", False),
    ("  8:  Utext \u2190 \u2205", False),
    ("  9:  for each (document, page) pair (d, p) do", False),
    (" 10:      x \u2190 concatenation of text blocks of S on (d, p)", False),
    (" 11:      Utext \u2190 Utext \u222a BalancedChunks(x, \u03c4)", False),
    (" 12:  Uvis \u2190 { c(v) : v visual }", False),
    (" 13:  for each u \u2208 Utext \u222a Uvis do", False),
    (" 14:      z(u) \u2190 EmbedText(u);  z(u) \u2190 z(u) / \u2016z(u)\u2016",
     False),
    (" 15:  Imm \u2190 FlatIP(Utext \u222a Uvis)", False),
    (" 16:  Itext \u2190 FlatIP(Utext)      \u25b7 same vectors, visual "
     "excluded", False),
    (" 17:  M \u2190 metadata records for Utext \u222a Uvis", False),
    (" 18:  return Imm, Itext, M", False),
])

A.gap(6)
A.algorithm("Algorithm 2", [
    ("Algorithm 2  Online multimodal query", True),
    ("Input: query q; mode m \u2208 {mrag, text-only}; depth k = 5", False),
    ("Output: grounded answer a", False),
    ("  1:  z \u2190 EmbedText(q);  z \u2190 z / \u2016z\u2016", False),
    ("  2:  I \u2190 Imm if m = mrag else Itext", False),
    ("  3:  R \u2190 TopK(I, z, k)      \u25b7 exact inner product = cosine",
     False),
    ("  4:  C \u2190 \u27e8 \u27e9;  P \u2190 \u2205   \u25b7 text context; "
     "image attachments", False),
    ("  5:  for each segment s \u2208 R in rank order do", False),
    ("  6:      if type(s) = text then", False),
    ("  7:          append (source(s), text(s)) to C", False),
    ("  8:      else", False),
    ("  9:          P \u2190 P \u222a { crop(s) }   \u25b7 original image, not "
     "the caption", False),
    (" 10:          append (source(s), caption(s), ref to crop(s)) to C",
     False),
    (" 11:  a \u2190 Generate(Prompt(q, C), images = P)", False),
    (" 12:  return a", False),
])
A.gap(6)

A.sub("E. Caching and reproducibility")
A.body(
    "Captions are cached per document by segment identifier, and embeddings "
    "under a hash of the exact text embedded plus the embedding model name, so "
    "a rerun regenerates neither. Keying that cache by content rather than "
    "position makes the text vectors shared between the two indexes provably "
    "identical, making the controlled comparison of Section IV-D exact. "
    "Deployment names, vector counts and index type go to a "
    "run-metadata file at build time.")

# -------------------------------------------------------------- SECTION VI
A.head("VI. Experimental Setup and Dataset")

A.sub("A. Corpus")
A.body(
    "The corpus is five publicly available manufacturer datasheets, listed in "
    "Table II. Selection used one criterion: each had to contain both a pinout "
    "or package diagram and a dense electrical-characteristics or timing "
    "table, so every document could feed both question pools. They span two "
    "orders of magnitude in length, from a 44-page linear-regulator datasheet "
    "to a 642-page microcontroller reference manual.")

A.caption("TABLE II.    CORPUS COMPOSITION AFTER PARSING")
A.table(
    ["Document", "Pages", "Text blocks", "Figures", "Tables"],
    [["RP2040", "642", "6,414", "140", "929"],
     ["ATmega328P", "653", "3,123", "708", "338"],
     ["STM32F103C8", "114", "528", "54", "85"],
     ["ESP32-WROOM-32E/32UE", "52", "448", "17", "39"],
     ["LM317", "44", "222", "68", "15"],
     ["Total", "1,505", "10,735", "987", "1,406"]],
    [1560, 620, 900, 780, 810])
A.gap(6)

A.sub("B. Parsing configuration")
A.body(
    "Parsing used MinerU 2.5 [3] (package version 3.4.5) with the pipeline "
    "backend on CPU. The 642-page RP2040 manual was parsed in 32-page batches "
    "with page offsets restored on concatenation, since a single pass over a "
    "document that size exceeded available memory. Parsing produced 13,128 "
    "typed segments, 10,735 of them text blocks and 2,393 figures or tables.")

A.sub("C. Models and index")
A.body(
    "Table III lists the full configuration. All three model roles were served "
    "through Azure OpenAI and reached only through the two-function boundary "
    "of Section IV-E. Captioning used the smaller vision deployment, since it "
    "runs once per visual segment across the corpus, and generation the "
    "stronger one, since it runs once per query. Every caption came from the "
    "same deployment, so no caption-model variation confounds the comparison.")

A.caption("TABLE III.    PIPELINE AND INDEX CONFIGURATION")
A.table(
    ["Component", "Configuration"],
    [["Parser", "MinerU 2.5 [3], v3.4.5, pipeline backend"],
     ["Captioning model", "GPT-5.6 Luna (Azure OpenAI)"],
     ["Generation model", "GPT-5.6 Sol (Azure OpenAI)"],
     ["Embedding model", "text-embedding-3-large, 3072 dimensions"],
     ["Normalization", "L2, unit vectors"],
     ["Vector store", "FAISS IndexFlatIP, exact search"],
     ["M-RAG index", "3,691 vectors (1,298 text, 2,393 caption)"],
     ["Text-only index", "1,298 vectors (text only)"],
     ["Chunk target", "approx. 400 whitespace tokens, page-grouped"],
     ["Retrieval depth", "k = 5"]],
    [1350, 3320])
A.gap(6)

A.sub("D. Question set")
A.body(
    "The evaluation set holds 18 questions written by hand against the source "
    "PDFs and distributed across all five documents: 13 visual-required and 5 "
    "prose controls. Every visual-required question was checked against its "
    "source to confirm the value appears in a figure or table and is not "
    "restated in prose, and each control was confirmed answerable from prose "
    "alone. One example of each: \u201cIn the ATmega328P 28-pin PDIP pinout, "
    "which physical pin carries PD1/TXD?\u201d, ground truth pin 3, which "
    "appears only in the diagram, and \u201cHow many UART interfaces does the "
    "ESP32 have?\u201d, ground truth three, which appears in prose.")

A.sub("E. Protocol and grading")
A.body(
    "Each question ran through both configurations at k = 5, giving 36 runs "
    "that logged the retrieved segment identifiers, the generated answer and "
    "the generation deployment name. All 36 were then graded by hand on two "
    "independent fields. Retrieval hit is a boolean recording whether the "
    "top-k set contained a segment carrying evidence sufficient for the "
    "ground-truth answer, judged from the retrieved identifiers before the "
    "model's answer was read. Answer score takes one of four values: correct, "
    "partially correct, incorrect, or no answer. Correct requires the exact "
    "value with units and any minimum, typical and maximum distinction; "
    "partially correct covers part of a multi-part ground truth; no answer is "
    "an explicit statement that the evidence was insufficient. Accuracy in "
    "Section VII counts only correct. At this scale an automated judge would "
    "itself have needed validation against human grades.")

# ------------------------------------------------------------- SECTION VII
A.head("VII. Results and Performance Analysis")

A.sub("A. Main comparison")
A.body(
    "Table IV reports retrieval hit rate and answer accuracy for both "
    "configurations by question split. On the thirteen visual-required "
    "questions the multimodal index improved both quantities by 61.5 "
    "percentage points; the baseline recorded no hit and no correct answer. H1 "
    "is supported. Fig. 6 plots the same comparison.")

A.caption("TABLE IV.    RETRIEVAL HIT RATE AND ANSWER ACCURACY BY QUESTION "
          "SPLIT")
A.table(
    ["Question split", "n", "Method", "Retrieval hit rate", "Answer accuracy"],
    [["Visual-required", "13", "M-RAG", "61.5% (8/13)", "61.5% (8/13)"],
     ["Visual-required", "13", "Text-only", "0.0% (0/13)", "0.0% (0/13)"],
     ["Prose control", "5", "M-RAG", "80.0% (4/5)", "80.0% (4/5)"],
     ["Prose control", "5", "Text-only", "80.0% (4/5)", "80.0% (4/5)"],
     ["All questions", "18", "M-RAG", "66.7% (12/18)", "66.7% (12/18)"],
     ["All questions", "18", "Text-only", "22.2% (4/18)", "22.2% (4/18)"]],
    [1080, 480, 780, 1165, 1165], header_size=7.0)
A.gap(6)

A.picture(FIG6, 3.24)
A.caption("Fig. 6.    Answer accuracy by question split over the 18 "
          "hand-graded questions. The retrieval hit rate is identical to "
          "accuracy in every cell, which is the finding developed in "
          "Section VII-C.", size=7.5, keep=False)

A.body(
    "The baseline's 0.0% is structural, the empirical form of the coverage "
    "argument in Section III-A: its index holds no vector derived from any "
    "figure or table, so no value of k could have reached the evidence. The "
    "exact zero also checks the question set, since a question misclassified "
    "as visual-required would have given the baseline something to retrieve.")
A.body(
    "On the five prose controls both configurations retrieved correctly on "
    "four and answered four correctly. Adding 2,393 caption vectors, an "
    "increase of 184% in index size, displaced correct prose evidence on no "
    "control question, so H2 is supported at this sample size. The single "
    "control failure was shared: on the STM32F103x8/xB DMA circular-buffer "
    "question both missed the relevant prose chunk and declined to answer, "
    "which reflects chunking or embedding, not modality.")

A.sub("B. Answer-score distribution")
A.body(
    "The accuracy column of Table IV compresses four answer grades into one "
    "number. Over the 36 "
    "runs, on the visual-required split M-RAG scored 8 correct, 1 incorrect "
    "and 4 no answer, against 0 correct, 1 partially correct, 1 incorrect and "
    "11 no answer for the baseline. On the prose controls both returned 4 "
    "correct and 1 no answer.")

A.sub("C. Retrieval failure versus generation failure")
A.body(
    "Recording retrieval hit and answer score as independent fields separates "
    "the two failure modes, and the outcome is unambiguous. Across all 18 "
    "questions M-RAG achieved a retrieval hit on 12 and answered correctly on "
    "exactly those 12. Conditional answer accuracy given a retrieval hit was "
    "12 of 12.")
A.body(
    "Every M-RAG failure was thus a retrieval failure, which localises the "
    "bottleneck precisely. The generation stage, supplied with original crops "
    "as described in Section IV-C, extracted the correct value from every "
    "table and diagram it was given, including exact pin numbers, a "
    "junction-to-board thermal resistance and several minimum, typical and "
    "maximum triples. That is direct evidence for the deferred-attachment "
    "design: had captions alone reached the generator, transcription loss "
    "would have been expected to produce errors on retrieved-but-misread "
    "segments, and none occurred. Improving this system further is a retrieval "
    "problem.")
A.body(
    "Abstention behaviour points the same way. Of the six questions M-RAG "
    "missed at retrieval, five produced an explicit statement that the "
    "evidence was insufficient and one an incorrect answer. Of the baseline's "
    "14 misses, 12 produced no answer, one a partially correct answer and one "
    "an incorrect one. Both configurations fail loudly, the preferable mode in "
    "technical documentation, where a confident wrong pin number costs more "
    "than an acknowledged gap.")

A.sub("D. Failure analysis")
A.body(
    "The five visual-required retrieval misses concentrated in two documents: "
    "two ESP32-WROOM-32E/32UE electrical values, two RP2040 values, and the "
    "LM317 line-regulation question, the single case producing an incorrect "
    "answer instead of an absent one. They share a pattern. Each target is one "
    "row inside a large multi-row specification table. The parser often emits "
    "such a table as several adjacent crops, and the caption of any one "
    "fragment is dominated by whichever parameters it happens to contain, so a "
    "query naming one parameter competes against many captions of similar "
    "shape and length. This is fragment-level caption dilution, not an "
    "inability of the model to read the values, and Section VIII proposes two "
    "remedies.")
A.body(
    "The one partially correct baseline answer is instructive about the "
    "question set. For the STM32 question asking minimum and maximum ADC "
    "conversion times at a 14 MHz ADC clock, the prose supplies the 1 \u00b5s "
    "minimum but not the 18 \u00b5s maximum, which appears only in the timing "
    "table. The baseline retrieved the prose and produced half the ground "
    "truth, so classifying it as visual-required is correct in the strict "
    "sense used here.")

A.sub("E. Threats to validity")
A.body(
    "Four limitations qualify these results. The question set contains 18 "
    "items, so the percentages carry wide confidence intervals; the 61.5-point "
    "gap survives that concern, while the 80.0% parity on five controls "
    "establishes only the absence of a large regression. Grading was performed "
    "by the authors rather than independent annotators, which admits unblinded "
    "bias, though both fields are largely objective and retrieval was judged "
    "from segment identifiers before the answer was read. The corpus is one "
    "domain and five documents, leaving the cross-domain claim open. And the "
    "questions were written after the pipeline was built, which risks "
    "selecting for its strengths; that M-RAG still missed 5 of 13 "
    "visual-required retrievals suggests the set was not tuned to be easy.")

# ------------------------------------------------------------ SECTION VIII
A.head("VIII. Conclusion and Future Work")
A.body(
    "This paper implemented and evaluated a multimodal retrieval-augmented "
    "generation pipeline for technical document understanding, generalizing "
    "the architecture-domain system of [1] to hardware and electronics "
    "datasheets. Visual regions become retrievable through dense factual "
    "captioning, one text encoder places prose chunks and visual surrogates in "
    "a single metric space, and the original crops reach the generator in "
    "place of their captions. Against a text-only baseline sharing the "
    "identical code path and text vectors, answer accuracy on questions whose "
    "evidence exists only in figures and tables rose from 0.0% to 61.5%, "
    "retrieval hit rate improved identically, and the two matched at 80.0% on "
    "prose controls. Every failure was a retrieval failure: on all 12 "
    "questions where the correct evidence was retrieved, the answer was "
    "correct.")
A.body(
    "These results validate the pipeline within one domain and leave the "
    "cross-domain claim open. Extending the evaluation to a structurally "
    "different document class, such as scientific papers or engineering "
    "service manuals, over the same code path and a split evaluation set, is "
    "the principal remaining item. Nothing in the architecture is specific to "
    "datasheets beyond the data source and the wording of the questions, so "
    "that is data-collection work, not re-architecture.")
A.body(
    "The failure analysis points to four further directions. Retrieval over "
    "table fragments is the identified bottleneck: merging adjacent crops "
    "belonging to one logical table before captioning, or indexing a per-row "
    "representation alongside the per-crop caption, should address the "
    "dilution of Section VII-D. A hybrid of dense retrieval with lexical "
    "matching over parameter symbols and numeric literals would suit a domain "
    "whose queries name exact identifiers. The question set should be enlarged "
    "and graded by independent annotators, with an automated judge admitted "
    "only once calibrated against human grades. And since all model access "
    "sits behind the two functions of Section IV-E, measuring the accuracy "
    "cost of substituting locally served open-weight models would price an "
    "on-premise deployment directly.")

# The source styles reference entries as Heading 3, which renders them at 9 pt.
# IEEE sets references at 8 pt; the runs carry no explicit size, so they have to
# be set here rather than on the style.
_refs = 0
for _p in doc.paragraphs:
    if _p.style.name == "Heading 3" and _p.text.strip().startswith("["):
        for _r in _p.runs:
            _r.font.size = Pt(8)
        _refs += 1
print(f"set {_refs} references to 8 pt")

# Drop the source's blank spacer paragraphs. Done last, so anchors taken on
# them earlier (the empty heading preceding "References") stayed valid.
_dropped = 0
for _blank in _SOURCE_BLANKS:
    _parent = _blank._p.getparent()
    if _parent is not None:
        _parent.remove(_blank._p)
        _dropped += 1
print(f"dropped {_dropped} blank source paragraphs")

doc.save(str(DST))
print("saved:", DST)
