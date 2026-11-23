"""Single source of visual styling for the M-RAG demo.

Streamlit's own heading sizes and control chrome shift between releases, so
every type-scale and card decision the demo depends on lives here rather than
relying on component defaults. Motion is CSS-only: no JavaScript and no
external assets, so the demo behaves identically offline.
"""

import streamlit as st


_CSS = """
<style>
    :root {
        --mrag-ink: #111827;
        --mrag-ink-soft: #4B5563;
        --mrag-ink-muted: #6B7280;
        --mrag-line: #E5E7EB;
        --mrag-line-strong: #D1D5DB;
        --mrag-blue: #2563EB;
        --mrag-violet: #7C3AED;
        --mrag-gradient: linear-gradient(120deg, #2563EB 0%, #7C3AED 100%);
    }

    .stApp {
        color: var(--mrag-ink);
        background: linear-gradient(180deg, #FFFFFF 0%, #F7F9FF 38%, #F4F7FF 100%);
        background-attachment: fixed;
    }

    .block-container {
        max-width: 1320px;
        padding-top: 2.1rem;
        padding-bottom: 7rem;
    }

    /* ---------------------------------------------------------- header */

    .mrag-header {
        margin-bottom: 1.15rem;
    }

    .mrag-wordmark {
        margin: 0;
        font-size: 27px;
        font-weight: 700;
        line-height: 1.15;
        letter-spacing: -0.028em;
        background: var(--mrag-gradient);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        -webkit-text-fill-color: transparent;
    }

    .mrag-sub {
        max-width: 680px;
        margin: 0.4rem 0 0;
        color: var(--mrag-ink-soft);
        font-size: 15px;
        line-height: 1.5;
    }

    .mrag-rule {
        height: 1px;
        margin: 1.15rem 0 1.35rem;
        border: 0;
        background: linear-gradient(
            90deg,
            rgba(37, 99, 235, 0.32) 0%,
            rgba(124, 58, 237, 0.22) 34%,
            rgba(229, 231, 235, 0) 100%
        );
    }

    .mrag-section-label {
        margin: 0 0 0.7rem;
        color: #374151;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.075em;
        text-transform: uppercase;
    }

    .mrag-count {
        margin-left: 0.4rem;
        color: var(--mrag-ink-muted);
        font-weight: 600;
        letter-spacing: 0.03em;
    }

    /* ------------------------------------------------------- mode pill */

    div[data-testid="stSegmentedControl"],
    div[data-testid="stButtonGroup"] {
        width: fit-content;
        padding: 4px;
        border: 1px solid var(--mrag-line-strong);
        border-radius: 999px;
        background: #FFFFFF;
        box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
    }

    div[data-testid="stSegmentedControl"] button,
    div[data-testid="stButtonGroup"] button {
        min-height: 36px;
        padding-right: 1.05rem;
        padding-left: 1.05rem;
        border-radius: 999px !important;
        font-size: 13.5px;
        font-weight: 600;
    }

    div[data-testid="stSegmentedControl"] button[aria-checked="true"],
    div[data-testid="stButtonGroup"] button[aria-checked="true"] {
        background: var(--mrag-gradient) !important;
        color: #FFFFFF !important;
        border-color: transparent !important;
    }

    .mrag-mode-note {
        margin: 0.5rem 0 0;
        color: var(--mrag-ink-muted);
        font-size: 12.5px;
        line-height: 1.45;
    }

    /* ----------------------------------------------------- chat bubbles */

    div[data-testid="stChatMessage"] {
        padding: 0.9rem 1.05rem;
        border: 1px solid var(--mrag-line);
        border-radius: 14px;
        background: #FFFFFF;
        box-shadow: 0 1px 2px rgba(17, 24, 39, 0.035);
    }

    div[data-testid="stChatMessage"]:has(.mrag-agent-anchor) {
        border-top: 2px solid transparent;
        background:
            linear-gradient(#FFFFFF, #FFFFFF) padding-box,
            var(--mrag-gradient) border-box;
    }

    div[data-testid="stChatMessage"] p,
    div[data-testid="stChatMessage"] li {
        font-size: 15.5px;
        line-height: 1.58;
    }

    /* Streamlit's stock avatars are material icons that read as clip art here.
       They become a plain dot: grey for the person, gradient for the agent. */
    div[data-testid^="stChatMessageAvatar"] {
        width: 22px;
        height: 22px;
        min-width: 22px;
        margin-top: 3px;
        border: none;
        border-radius: 50%;
        background: #E5E7EB;
        color: transparent;
        font-size: 0;
    }

    div[data-testid^="stChatMessageAvatar"] * {
        display: none;
    }

    div[data-testid="stChatMessageAvatarAssistant"] {
        background: var(--mrag-gradient);
    }

    /* --------------------------------------------------- status stages */

    .mrag-status {
        display: flex;
        flex-direction: column;
        gap: 0.3rem;
        margin-bottom: 0.15rem;
    }

    .mrag-stage {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--mrag-ink-muted);
        font-size: 13.5px;
        font-weight: 500;
        line-height: 1.4;
        animation: mrag-lift 0.22s ease-out both;
    }

    .mrag-stage.done .mrag-tick {
        color: #059669;
        font-weight: 700;
    }

    .mrag-stage.active {
        color: var(--mrag-ink);
        font-weight: 600;
    }

    .mrag-stage.active .mrag-stage-text {
        background: linear-gradient(
            90deg,
            #9CA3AF 0%,
            #2563EB 42%,
            #7C3AED 52%,
            #9CA3AF 100%
        );
        background-size: 220% 100%;
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        -webkit-text-fill-color: transparent;
        animation: mrag-shimmer 1.6s linear infinite;
    }

    .mrag-dots {
        display: inline-flex;
        gap: 3px;
        margin-left: 1px;
    }

    .mrag-dots i {
        width: 3px;
        height: 3px;
        border-radius: 50%;
        background: var(--mrag-violet);
        animation: mrag-pulse 1.1s ease-in-out infinite;
    }

    .mrag-dots i:nth-child(2) { animation-delay: 0.18s; }
    .mrag-dots i:nth-child(3) { animation-delay: 0.36s; }

    .mrag-trace {
        margin: 0.1rem 0 0.75rem;
        color: var(--mrag-ink-muted);
        font-size: 12.5px;
        font-weight: 500;
        animation: mrag-lift 0.22s ease-out both;
    }

    .mrag-cursor {
        display: inline-block;
        width: 2px;
        height: 1em;
        margin-left: 2px;
        vertical-align: text-bottom;
        background: var(--mrag-blue);
        animation: mrag-blink 0.9s step-end infinite;
    }

    /* -------------------------------------------------------- provenance */

    .mrag-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.34rem;
        margin-bottom: 0.6rem;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        font-size: 11.5px;
        font-weight: 700;
        letter-spacing: 0.055em;
        text-transform: uppercase;
        animation: mrag-scale 0.18s ease-out both;
    }

    .mrag-badge.grounded { background: #EFF6FF; color: #1D4ED8; }
    .mrag-badge.general { background: #F5F3FF; color: #6D28D9; }
    .mrag-badge.uncovered { background: #FEF3C7; color: #B45309; }
    .mrag-badge.unsupported { background: #FEF2F2; color: #B91C1C; }

    .mrag-cite {
        display: inline-block;
        margin: 0 2px;
        padding: 0.02rem 0.34rem;
        border: 1px solid #DBEAFE;
        border-radius: 5px;
        background: #EFF6FF;
        color: #1D4ED8;
        font-size: 11.5px;
        font-weight: 700;
        vertical-align: 1px;
        animation: mrag-scale 0.16s ease-out both;
    }

    .mrag-foot {
        margin-top: 0.9rem;
        padding-top: 0.7rem;
        border-top: 1px solid var(--mrag-line);
        color: var(--mrag-ink-muted);
        font-size: 12.5px;
        font-weight: 500;
        line-height: 1.45;
    }

    /* ------------------------------------------------------ why panel */

    div[data-testid="stExpander"] details {
        border: 1px solid var(--mrag-line);
        border-radius: 10px;
        background: #FCFDFF;
    }

    div[data-testid="stExpander"] summary p {
        font-size: 13px !important;
        font-weight: 600;
        color: #374151;
    }

    .mrag-why {
        display: grid;
        grid-template-columns: 108px 1fr;
        gap: 0.34rem 0.7rem;
        font-size: 13px;
        line-height: 1.45;
    }

    .mrag-why dt {
        color: var(--mrag-ink-muted);
        font-weight: 600;
        letter-spacing: 0.03em;
        text-transform: uppercase;
        font-size: 11.5px;
        padding-top: 1px;
    }

    .mrag-why dd {
        margin: 0;
        color: var(--mrag-ink);
    }

    /* --------------------------------------------------- evidence cards */

    /* The bordered container Streamlit gives st.container(border=True) has
       moved test id between releases: it is stVerticalBlockBorderWrapper on
       1.4x and a directly-bordered stVerticalBlock from 1.6x. Both are matched
       so the cards keep their state styling across either. The child-scoped
       form matters: an unscoped :has would also match every ancestor block. */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mrag-card),
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card) {
        border-color: var(--mrag-line);
        border-radius: 12px;
        background: #FFFFFF;
        animation: mrag-lift 0.24s ease-out both;
        /* Deliberately no opacity transition: Streamlit reuses card nodes
           between reruns, so a cited/uncited swap would animate, and a stalled
           timeline would strand the card at the wrong opacity. */
        transition: border-color 0.28s ease, box-shadow 0.28s ease;
    }

    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mrag-card.d2),
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card.d2) { animation-delay: 0.06s; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mrag-card.d3),
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card.d3) { animation-delay: 0.12s; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mrag-card.d4),
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card.d4) { animation-delay: 0.18s; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mrag-card.d5),
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card.d5) { animation-delay: 0.24s; }

    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mrag-card.uncited),
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card.uncited) {
        opacity: 0.58;
    }

    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .mrag-card.cited),
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card.cited) {
        border-color: #BFDBFE !important;
        box-shadow: inset 3px 0 0 0 var(--mrag-blue);
    }

    .mrag-card-meta {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.36rem;
        margin-bottom: 0.55rem;
        color: var(--mrag-ink-muted);
        font-size: 12.5px;
        font-weight: 500;
        line-height: 1.4;
    }

    .mrag-label {
        display: inline-flex;
        padding: 0.1rem 0.36rem;
        border-radius: 5px;
        background: #F3F4F6;
        color: #374151;
        font-size: 11.5px;
        font-weight: 700;
    }

    .mrag-card.cited .mrag-label {
        background: var(--mrag-gradient);
        color: #FFFFFF;
    }

    .mrag-type {
        display: inline-flex;
        padding: 0.12rem 0.42rem;
        border-radius: 999px;
        background: #EFF6FF;
        color: #1D4ED8;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.045em;
        text-transform: uppercase;
    }

    .mrag-type.table { background: #F5F3FF; color: #6D28D9; }
    .mrag-type.figure { background: #ECFDF5; color: #047857; }

    .mrag-score {
        margin-left: auto;
        font-variant-numeric: tabular-nums;
        font-size: 12px;
    }

    .mrag-snippet {
        color: var(--mrag-ink);
        font-size: 13.5px;
        line-height: 1.5;
        overflow-wrap: anywhere;
    }

    .mrag-empty {
        padding: 1.4rem 0.2rem;
        color: var(--mrag-ink-muted);
        font-size: 13.5px;
        line-height: 1.5;
        text-align: center;
    }

    /* Datasheet crops range from a two-line table row to a full page, so they
       are capped to keep every card scannable at a glance. */
    div[data-testid="stImage"] img {
        max-height: 300px;
        width: auto !important;
        max-width: 100%;
        margin: 0 auto;
        border: 1px solid var(--mrag-line);
        border-radius: 8px;
        background: #FFFFFF;
        object-fit: contain;
    }

    div[data-testid="stImage"] {
        display: flex;
        justify-content: center;
    }

    /* ------------------------------------------------- suggestion chips */

    div[data-testid="stButton"] button {
        min-height: 40px;
        border: 1px solid #E3E8F2;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.72);
        color: #374151;
        font-size: 13.5px;
        font-weight: 500;
        transition: border-color 0.18s ease, background 0.18s ease;
    }

    div[data-testid="stButton"] button:hover {
        border-color: #BFDBFE;
        background: #F8FAFF;
        color: #1D4ED8;
    }

    /* -------------------------------------------------------- composer */

    div[data-testid="stChatInput"] {
        border-color: var(--mrag-line-strong);
        border-radius: 12px;
        background: #FFFFFF;
        box-shadow: 0 2px 14px rgba(37, 99, 235, 0.07);
    }

    div[data-testid="stChatInput"] textarea {
        font-size: 15.5px;
    }

    /* ------------------------------------------------------- keyframes */

    @keyframes mrag-shimmer {
        from { background-position: 120% 0; }
        to { background-position: -120% 0; }
    }

    @keyframes mrag-pulse {
        0%, 100% { opacity: 0.25; transform: translateY(0); }
        50% { opacity: 1; transform: translateY(-2px); }
    }

    /* Entrance motion animates transform only, never opacity. A stalled
       animation timeline pins a running animation to its first frame, so a
       fade-in would leave content permanently invisible; a held transform
       only leaves it a few pixels off. Nothing here can hide the evidence. */
    @keyframes mrag-lift {
        from { transform: translateY(6px); }
        to { transform: translateY(0); }
    }

    @keyframes mrag-scale {
        from { transform: scale(0.92); }
        to { transform: scale(1); }
    }

    @keyframes mrag-blink {
        50% { opacity: 0; }
    }

    @media (prefers-reduced-motion: reduce) {
        .mrag-stage,
        .mrag-trace,
        .mrag-badge,
        .mrag-cite,
        .mrag-cursor,
        .mrag-dots i,
        .mrag-stage.active .mrag-stage-text,
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.mrag-card) {
            animation: none !important;
        }
    }

    @media (max-width: 900px) {
        .block-container {
            padding-right: 1rem;
            padding-left: 1rem;
        }

        div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }

        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            min-width: 100% !important;
            width: 100% !important;
            flex: 1 1 100% !important;
        }
    }
</style>
"""


def inject() -> None:
    """Apply the demo stylesheet once per script run."""
    st.markdown(_CSS, unsafe_allow_html=True)
