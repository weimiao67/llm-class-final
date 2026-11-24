"""Build the presentation deck (docs/slides/housing-analyst.pptx) and its charts.

Every number on the slides is read from the saved eval summaries in evaluation/reports/, so the
deck can't drift from docs/evaluation.md. Import the .pptx into Google Slides (upload it to
Drive, then "Open with Google Slides"), or use File → Import slides.

    uv run --with python-pptx --with matplotlib python docs/slides/build_slides.py

Screenshots in docs/slides/img/ are taken from the running UI (see docs/demo.md); slides that
use them get a placeholder box if a file is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import PP_ALIGN  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
IMG = OUT / "img"
REPORTS = ROOT / "evaluation" / "reports"
RUNS = {
    "Llama-3.2-3B (base)": "20261123-064147-llama-3.2-3b-instruct-planner-v2",
    "Qwen2.5-3B (base)": "20261123-075101-qwen2.5-3b-instruct-planner-v2",
    "Qwen2.5-3B + LoRA, data v1": "20261123-171002-qwen2.5-3b-lora-93a8b1a171",
    "Qwen2.5-3B + LoRA, data v2": "20261123-191702-qwen2.5-3b-lora-f261a5f4d7",
}
FINAL, BASE = "Qwen2.5-3B + LoRA, data v2", "Qwen2.5-3B (base)"

# Light-mode chart colors: the highlight (series 1) and a context gray, validated with the
# dataviz skill's validator (contrast >= 3:1, CVD and normal-vision separation pass).
BLUE, GRAY = "#2a78d6", "#86857e"
INK, INK_2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df"
RGB = {
    k: RGBColor.from_string(v.lstrip("#"))
    for k, v in {
        "ink": INK,
        "ink2": INK_2,
        "blue": BLUE,
        "gray": GRAY,
        "panel": "#f1f0ec",
        "white": "#ffffff",
    }.items()
}
FONT = "Arial"


def summary(run: str) -> dict:
    return json.loads((REPORTS / run / "summary.json").read_text())


def rate(s: dict, key: str, family: str | None = None) -> float:
    block = s["families"][family] if family else s["overall"]
    return block[key]["rate"] * 100


# ---- charts ----------------------------------------------------------------------------------


def _style(ax):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=12, length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")


def chart_accuracy(path: Path) -> None:
    """Execution accuracy by model: the final model highlighted, the others context gray."""
    names = list(RUNS)[::-1]  # final model on top
    values = [rate(summary(RUNS[n]), "execution_accuracy") for n in names]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=200, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    colors = [BLUE if n == FINAL else GRAY for n in names]
    bars = ax.barh(names, values, color=colors, height=0.62, edgecolor=SURFACE, linewidth=2)
    for bar, v, n in zip(bars, values, names, strict=True):
        ax.text(
            v + 1.5,
            bar.get_y() + bar.get_height() / 2,
            f"{v:.1f}%",
            va="center",
            fontsize=13,
            color=INK,
            fontweight="bold" if n == FINAL else "normal",
        )
    _style(ax)
    ax.tick_params(axis="y", labelsize=13, labelcolor=INK)
    ax.set_title(
        "Execution accuracy, eval set v1 (131 data cases)",
        loc="left",
        fontsize=14,
        color=INK,
        pad=12,
    )
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def chart_families(path: Path) -> None:
    """Turn success per question family: base Qwen vs. the fine-tuned model."""
    base, final = summary(RUNS[BASE]), summary(RUNS[FINAL])
    families = sorted(final["families"], key=lambda f: rate(final, "turn_success", f))
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=200, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    y = range(len(families))
    h = 0.38
    ax.barh(
        [i + h / 2 for i in y],
        [rate(base, "turn_success", f) for f in families],
        h,
        color=GRAY,
        label="Qwen2.5-3B base",
        edgecolor=SURFACE,
        linewidth=2,
    )
    ax.barh(
        [i - h / 2 for i in y],
        [rate(final, "turn_success", f) for f in families],
        h,
        color=BLUE,
        label="+ LoRA (data v2)",
        edgecolor=SURFACE,
        linewidth=2,
    )
    ax.set_yticks(list(y), [f.replace("_", " ") for f in families])
    _style(ax)
    ax.tick_params(axis="y", labelsize=12, labelcolor=INK)
    # No chart title (the slide title names it); the legend sits above the bars, clear of them.
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncol=2,
        frameon=False,
        fontsize=12,
        labelcolor=INK,
        borderaxespad=0.3,
    )
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


# ---- slide helpers ---------------------------------------------------------------------------


def text_box(
    slide, left, top, width, height, lines, size=20, color="ink", bold=False, align=PP_ALIGN.LEFT
):
    """Lines are strings; a line starting with '• ' becomes a bullet-like paragraph."""
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    for i, line in enumerate(lines):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.alignment = align
        p.space_after = Pt(8)
        run = p.add_run()
        run.text = line
        run.font.size, run.font.name, run.font.bold = Pt(size), FONT, bold
        run.font.color.rgb = RGB[color]
    return box


def card(
    slide,
    left,
    top,
    width,
    height,
    title,
    body,
    fill="panel",
    title_color="ink",
    body_size=12,
    body_align=None,
):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.adjustments[0] = 0.08
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGB[fill]
    shape.line.fill.background()
    frame = shape.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.15)
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = title
    run.font.size, run.font.bold, run.font.name = Pt(16), True, FONT
    run.font.color.rgb = RGB[title_color if fill == "panel" else "white"]
    # One paragraph per line: a "\n" inside a run's text is written literally, and PowerPoint
    # and Google Slides don't break on it, so every line of the body would run together.
    for line in body.split("\n") if body else []:
        q = frame.add_paragraph()
        q.alignment = body_align or PP_ALIGN.CENTER
        if body_align == PP_ALIGN.LEFT:
            q.space_before = Pt(6)
        r = q.add_run()
        r.text = line
        r.font.size, r.font.name = Pt(body_size), FONT
        r.font.color.rgb = RGB["ink2" if fill == "panel" else "white"]
    return shape


def arrow(slide, left, top, width=None, height=None):
    width, height = width or Inches(0.35), height or Inches(0.3)
    shape = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGB["gray"]
    shape.line.fill.background()


def image_or_placeholder(slide, path: Path, left, top, width=None, height=None):
    if path.exists():
        return slide.shapes.add_picture(str(path), left, top, width=width, height=height)
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, left, top, width or Inches(6), height or Inches(3.5)
    )
    shape.fill.background()
    shape.line.color.rgb = RGB["gray"]
    shape.text_frame.text = f"Screenshot: {path.name}"
    return shape


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)
        self.blank = self.prs.slide_layouts[6]

    def slide(self, title: str | None, notes: str):
        s = self.prs.slides.add_slide(self.blank)
        if title:
            text_box(
                s, Inches(0.6), Inches(0.35), Inches(12.1), Inches(0.9), [title], size=32, bold=True
            )
        s.notes_slide.notes_text_frame.text = notes
        return s

    def save(self, path: Path):
        self.prs.save(str(path))


# ---- the deck --------------------------------------------------------------------------------


def build() -> Path:
    IMG.mkdir(exist_ok=True)
    chart_accuracy(IMG / "chart_accuracy.png")
    chart_families(IMG / "chart_families.png")
    base, final = summary(RUNS[BASE]), summary(RUNS[FINAL])
    ex_base, ex_final = rate(base, "execution_accuracy"), rate(final, "execution_accuracy")
    ts_base, ts_final = rate(base, "turn_success"), rate(final, "turn_success")
    d = Deck()
    W = Inches(12.1)
    L = Inches(0.6)

    # 1. Title
    s = d.slide(
        None,
        "Introduce the project in one sentence: a small fine-tuned model plans the "
        "analysis; trusted code computes every number. Say what the audience will see: "
        "the approach, the fine-tuning results, and a live demo on AWS.",
    )
    text_box(s, L, Inches(2.3), W, Inches(1.2), ["Housing Market AI Analyst"], size=44, bold=True)
    text_box(
        s,
        L,
        Inches(3.6),
        W,
        Inches(1.2),
        ["A fine-tuned 3B model plans the analysis. Trusted code computes every number."],
        size=24,
        color="ink2",
    )
    text_box(
        s,
        L,
        Inches(5.6),
        W,
        Inches(0.8),
        ["LLM class final project  ·  <your name>  ·  github.com/weimiao67/llm-class-final"],
        size=16,
        color="ink2",
    )

    # 2. Project at a glance (for the instructor: what was built, by grading area)
    n_docs = len(list((ROOT / "docs").glob("*.md")))
    s = d.slide(
        "Project at a glance",
        "One slide that summarizes the whole project, organized by the rubric's three areas. "
        "Left: the model work (base-model comparison, LoRA fine-tune, validator-checked "
        "training data, the 200-case eval set, and the result). Middle: the inference "
        "pipeline and the sampling method, exposed as an API. Right: the AWS deployment, "
        "the documentation, and the demo. The rest of the talk goes through each in turn.",
    )
    text_box(
        s,
        L,
        Inches(1.25),
        W,
        Inches(1.0),
        [
            "A conversational analyst for U.S. city home values and rents (Zillow ZHVI and "
            "ZORI). A LoRA-fine-tuned 3B model plans each analysis; trusted code validates "
            "it, runs it as SQL, and computes every number."
        ],
        size=18,
        color="ink2",
    )
    glance = [
        (
            "Model · LoRA · evaluation",
            "• Compared Llama-3.2-3B, Phi-4-mini, and Qwen2.5-3B; fine-tuned Qwen with LoRA "
            "on SageMaker\n"
            "• 3,000 synthetic training examples, each checked against the real data and "
            "kept away from the eval set\n"
            f"• 200-case frozen eval set with gold plans: execution accuracy {ex_base:.1f}% "
            f"→ {ex_final:.1f}%, turn success {ts_base:.1f}% → {ts_final:.1f}%",
        ),
        (
            "Inference pipeline · sampling · API",
            "• Question → typed plan → validation against the data → parameterized SQL "
            "(DuckDB) → answer\n"
            "• Planning: greedy, JSON-schema constrained. Answers: T=0.3, top-p 0.9, with "
            "a check that every number is in the result\n"
            "• BM25 search over methodology notes; FastAPI endpoint with an API key",
        ),
        (
            "Deployment · docs · demo",
            "• Model on a SageMaker TGI endpoint; API and Streamlit UI on EC2 with Docker, "
            "scoped IAM role\n"
            f"• README and {n_docs} docs: architecture, model, sampling, evaluation, API, "
            "and runbooks for every AWS step\n"
            "• Unit tests and CI on every pull request; live demo with a scripted fallback",
        ),
    ]
    cw = Inches(3.9)
    for i, (title, body) in enumerate(glance):
        card(
            s,
            L + i * (cw + Inches(0.2)),
            Inches(2.45),
            cw,
            Inches(4.1),
            title,
            body,
            fill="panel",
            body_size=14,
            body_align=PP_ALIGN.LEFT,
        )
    text_box(
        s,
        L,
        Inches(6.75),
        W,
        Inches(0.5),
        ["Code, docs, eval reports, and this deck: github.com/weimiao67/llm-class-final"],
        size=14,
        color="ink2",
    )

    # 3. Problem
    s = d.slide(
        "The problem",
        "Even a simple question needs the right dataset, geography, period, "
        "a calculation, and the caveats. An LLM answering from memory invents numbers; one "
        "that writes SQL is hard to govern (injection, wrong joins, invented columns). The "
        "research question: can a small fine-tuned model plan these analyses reliably?",
    )
    text_box(
        s,
        L,
        Inches(1.4),
        Inches(7.2),
        Inches(5),
        [
            '"How did rents change in Denver over three years?"',
            "• Find the right dataset and series (rent index, smoothed, seasonally adjusted)",
            "• Resolve the city (30 Zillow city names exist in several counties of one state)",
            "• Filter the period, compute the change, note missing months",
            "• Explain what the index measures",
            "LLMs answering from memory invent numbers. LLM-written SQL is hard to govern.",
        ],
        size=20,
    )
    card(
        s,
        Inches(8.3),
        Inches(1.6),
        Inches(4.4),
        Inches(3.4),
        "Research question",
        "Can a small model, fine-tuned for this one job, reliably turn a plain-English "
        "question into the right analysis?\n\n"
        "How I check: 200 test questions it never saw in training. For each one, run the "
        "model's plan and the correct plan, and compare the results.",
        body_size=16,
    )

    # 3. Approach
    s = d.slide(
        "Approach: the model plans, code computes",
        "Walk the pipeline left to right. "
        "The model's only output is a typed tool call. The validator checks it against "
        "the data (cities, months, fields); the compiler makes parameterized SQL; DuckDB "
        "runs it. The model then writes one or two sentences from the result, and a check "
        "rejects any number not in the result.",
    )
    steps = [
        ("Question", "plain English"),
        ("Planner", "Qwen2.5-3B + LoRA\ntyped AnalysisPlan"),
        ("Validator", "cities, months,\nfields vs. data"),
        ("SQL + DuckDB", "parameterized,\nversioned Parquet"),
        ("Answer writer", "1–2 sentences\nfrom the result"),
        ("Number check", "every number\nin the result"),
    ]
    bw, gap, top = Inches(1.75), Inches(0.33), Inches(2.0)
    for i, (title, body) in enumerate(steps):
        x = L + i * (bw + gap)
        card(
            s,
            x,
            top,
            bw,
            Inches(1.6),
            title,
            body,
            fill="blue" if title in ("Planner", "Answer writer") else "panel",
        )
        if i < len(steps) - 1:
            arrow(s, x + bw + Inches(0.05), top + Inches(0.65), width=Inches(0.23))
    text_box(
        s,
        L,
        Inches(4.1),
        W,
        Inches(2.6),
        [
            "Blue = model calls.  Everything else is deterministic code, the same for every model.",
            "• Ambiguous city → the validator asks which one, instead of guessing",
            "• Methodology questions → BM25 search over reviewed Zillow methodology notes",
            "• Forecasts, advice, SQL requests → declined, with what the data can show instead",
        ],
        size=18,
    )

    # 4. Trust boundary
    s = d.slide(
        "Trust boundary",
        "This is the safety argument. The model can only fill a typed "
        "plan or decline. It cannot write SQL, touch tables, or put a number in front of "
        "the user that isn't in the result: the check regenerates the answer or falls back "
        "to a template written by code.",
    )
    card(
        s,
        L,
        Inches(1.5),
        Inches(5.9),
        Inches(4.6),
        "The model can",
        "Choose a tool: analyze, search_knowledge, respond\n\nFill a typed plan: metric, "
        "cities, state, months, operation, ranking\n\nAsk a clarifying question, or decline\n\n"
        "Write the prose of the answer",
    )
    card(
        s,
        Inches(6.8),
        Inches(1.5),
        Inches(5.9),
        Inches(4.6),
        "The model cannot",
        "Write SQL or code, name tables or files\n\nShow a number that isn't in the tool result "
        "(checked on every answer)\n\nPick a state the user didn't write (the validator asks)\n\n"
        "Follow instructions injected in the question (trained to ignore them)",
    )

    # 5. Model
    s = d.slide(
        "Model: choose a base, then fine-tune it",
        "Compared two families on the same "
        "prompt before training. Phi-4-mini couldn't be served on TGI 3.3.6 (partial "
        "rotary embeddings). Qwen beat Llama by 23.6 points of execution accuracy, so it "
        "was fine-tuned. LoRA on all projections, loss only on the tool call, one epoch "
        "on one A10G GPU in 37 minutes.",
    )
    llama = rate(summary(RUNS["Llama-3.2-3B (base)"]), "execution_accuracy")
    text_box(
        s,
        L,
        Inches(1.4),
        Inches(6.2),
        Inches(5),
        [
            "Base model comparison (execution accuracy)",
            f"• Llama-3.2-3B-Instruct: {llama:.1f}%",
            "• Phi-4-mini-instruct: not servable on TGI 3.3.6",
            f"• Qwen2.5-3B-Instruct: {ex_base:.1f}%  → selected",
            "Base failures were systematic: guessed city lists for statewide questions, wrong "
            "refusal kind, analyzing questions it should decline.",
        ],
        size=18,
    )
    card(
        s,
        Inches(7.2),
        Inches(1.5),
        Inches(5.5),
        Inches(4.4),
        "LoRA fine-tune",
        "r 16 · alpha 32 · dropout 0.05\nall attention + MLP projections\n\nloss on the final "
        "tool call only\nlr 2e-4, cosine · batch 16 · 1 epoch\n\nml.g5.xlarge (A10G) · 36.7 min "
        "· 8.5 GB\nmerged into the weights, served on TGI",
    )

    # 6. Training data
    s = d.slide(
        "Training data: generated, then verified",
        "The data is "
        "synthetic but correct by construction: the grammar writes the question and the "
        "gold call from the same slot values. Then every candidate runs through the "
        "project's own validator and tools, and anything close to the eval set is "
        "dropped. The trusted code doubles as a data-quality filter.",
    )
    funnel = [
        ("Phrase grammar", "40 templates,\n7 scenarios"),
        ("Execution filter", "gold call must run\non the real data"),
        ("Leakage filters", "no eval cities, plans,\nor near-duplicate questions"),
        ("3,000 examples", "2,661 train / 339 dev\n317 rejected"),
    ]
    bw = Inches(2.75)
    for i, (title, body) in enumerate(funnel):
        x = L + i * (bw + Inches(0.38))
        card(s, x, Inches(1.7), bw, Inches(1.7), title, body, fill="blue" if i == 3 else "panel")
        if i < 3:
            arrow(s, x + bw + Inches(0.02), Inches(2.4))
    text_box(
        s,
        L,
        Inches(3.9),
        W,
        Inches(3),
        [
            "Scenario mix: standard 690 · scope 570 · follow-up 480 · clarify 420 · refusal 420 · "
            "retry 240 · methodology 180",
            "• Dev questions use sentence shapes the model never trained on",
            "• Closest training question to any eval question: 3-gram similarity 0.597 "
            "(threshold 0.6)",
            "• Deterministic: same seed and code → same dataset, checked by sha256",
        ],
        size=18,
    )

    # 7. Sampling
    s = d.slide(
        "Sampling: exact plans, checked answers",
        "Two kinds of model "
        "calls, decoded differently. Plans: greedy, so runs are reproducible, and "
        "constrained by a structure-only JSON schema that also enforces city-or-state "
        "scope and valid state codes. Answers: sampled at T=0.3, top-p 0.9; any number "
        "not in the result triggers a greedy retry, then a code-written template.",
    )
    card(
        s,
        L,
        Inches(1.5),
        Inches(5.9),
        Inches(2.4),
        "Planning: greedy + JSON-schema constrained",
        "TGI masks tokens that would break the schema\nstructure-only schema (full one hung TGI)\n"
        "city-scoped OR state-scoped plan · 51 state codes",
    )
    card(
        s,
        Inches(6.8),
        Inches(1.5),
        Inches(5.9),
        Inches(2.4),
        "Answers: T=0.3, top-p 0.9",
        "every number must be in the tool result\nfail → greedy retry → template written by code",
    )
    text_box(
        s,
        L,
        Inches(4.2),
        W,
        Inches(2.8),
        [
            "Measured on the eval runs (fine-tuned model):",
            "• 89.7% of first sampled answers pass the number check (139 of 155)",
            "• Rejected answers: 11 miscomputed numbers (e.g. 33,821.90 instead of 3,382.19), "
            "5 stray integers",
            "• Planner retries: 25 for the base model → 0 after fine-tuning",
            "• Constraint on vs. off after fine-tuning: 89.3% vs. 90.1% (one case): the format "
            "is learned",
        ],
        size=17,
    )

    # 8. Results
    s = d.slide(
        "Results: fine-tuning closes the gap",
        f"Execution accuracy runs predicted and "
        f"gold plans and compares the result tables, as in text-to-SQL benchmarks. "
        f"Base Qwen {ex_base:.1f}% → fine-tuned {ex_final:.1f}%. Turn success, which also "
        f"scores clarifications, refusals, and methodology answers, {ts_base:.1f}% → "
        f"{ts_final:.1f}%. On eval v1.1 (four corrected gold plans): 92.1% and 94.5%.",
    )
    s.shapes.add_picture(str(IMG / "chart_accuracy.png"), L, Inches(1.3), width=Inches(7.6))
    card(
        s,
        Inches(8.6),
        Inches(1.5),
        Inches(4.1),
        Inches(1.4),
        f"{ts_final:.1f}%",
        f"turn success (base {ts_base:.1f}%)",
        fill="blue",
    )
    card(
        s,
        Inches(8.6),
        Inches(3.1),
        Inches(4.1),
        Inches(1.4),
        "100%",
        f"valid first output (base {rate(base, 'envelope_valid'):.0f}%)",
    )
    p50, p95 = final["overall"]["latency_ms_p50"] / 1000, final["overall"]["latency_ms_p95"] / 1000
    card(
        s,
        Inches(8.6),
        Inches(4.7),
        Inches(4.1),
        Inches(1.4),
        f"{p50:.1f} s / {p95:.1f} s",
        "latency p50 / p95 per turn",
    )

    # 9. By family
    s = d.slide(
        "Where fine-tuning helped",
        "Statewide questions (multi-city, aggregate) and "
        "refusal kinds (boundary, injection) improved the most: these were the base "
        "model's systematic failures. Single-city questions were already good and stayed "
        "at 100%.",
    )
    s.shapes.add_picture(str(IMG / "chart_families.png"), L, Inches(1.4), width=Inches(7.6))
    text_box(
        s,
        Inches(8.4),
        Inches(1.6),
        Inches(4.4),
        Inches(5),
        [
            "Biggest gains:",
            *(
                f"• {f.replace('_', ' ')}: {rate(base, 'turn_success', f):.0f}% → "
                f"{rate(final, 'turn_success', f):.0f}%"
                for f in ("multi_city", "aggregate", "boundary", "injection")
            ),
            "Methodology = chose the search tool; its answers aren't scored yet.",
            "Full per-family table and error analysis: docs/evaluation.md",
        ],
        size=17,
    )

    # 10. Deployment
    s = d.slide(
        "Deployment on AWS",
        "The model runs on a SageMaker real-time endpoint with "
        "TGI. The app (FastAPI agent + Streamlit UI) runs as two containers on one EC2 "
        "t3.small, about 70 cents a day with its address and disk. The instance role may "
        "only call this one endpoint, read the data prefix, and read the API key. The UI "
        "talks to the API "
        "like any client.",
    )
    boxes = [
        ("Browser / curl", "your IP only\nX-API-Key"),
        ("EC2 t3.small", "docker compose:\nStreamlit UI → FastAPI agent\nDuckDB over Parquet"),
        ("SageMaker endpoint", "TGI 3.3.6\nQwen2.5-3B + merged LoRA\nml.g5.2xlarge or g6 fallback"),
    ]
    bw = Inches(3.6)
    for i, (title, body) in enumerate(boxes):
        x = L + i * (bw + Inches(0.6))
        card(s, x, Inches(1.8), bw, Inches(2.0), title, body, fill="blue" if i == 2 else "panel")
        if i < 2:
            arrow(s, x + bw + Inches(0.12), Inches(2.65))
    text_box(
        s,
        L,
        Inches(4.3),
        W,
        Inches(2.6),
        [
            "• One Dockerfile, two images: API (no Streamlit) and UI (no model code)",
            "• Security group: UI and API ports from one address; IMDSv2; scoped instance role",
            "• Cost: app ~$0.70/day; endpoint ~$1.5/hour, deleted after every session",
            "• Runbooks with scripts for every step: docs/app-deployment.md, docs/deployment.md",
        ],
        size=18,
    )

    # 11. Demo
    s = d.slide(
        "Live demo",
        "Run the questions in order (script in docs/demo.md). For each, "
        "show the answer tab, then the evidence tab: the plan, the SQL with its "
        "parameters, the resolved cities, and the tool trace. Finish with curl against "
        "the API.",
    )
    text_box(
        s,
        L,
        Inches(1.4),
        Inches(6.4),
        Inches(5.6),
        [
            "1. What was Mead, CO's highest ZHVI month in 2025?",
            "2. Rank Colorado cities by ZHVI growth in 2025",
            "3. What about rent growth for the same cities and year?",
            "4. How did home values change in Oakwood, OH since 2020?",
            "5. What will Denver rent be next year?",
            "6. What is ZORI and how is it smoothed?",
            "7. curl the API: POST /v1/ask",
        ],
        size=19,
    )
    image_or_placeholder(s, IMG / "ui_rank.png", Inches(7.2), Inches(1.4), width=Inches(5.6))

    # 12. One fixed, one not
    s = d.slide(
        "One failure fine-tuning fixed, one it didn't",
        "Fixed: the first LoRA round "
        "had no search_knowledge examples, so methodology questions collapsed from 73% "
        "to 27%. Data v2 added them: it chose the search tool every time (100%). Note: the "
        "eval scored only that choice; the answers themselves aren't scored yet. "
        "Not fixed: 'What about rent?' right after a "
        "state ranking. All 50 metric-switch follow-ups in the training data follow a "
        "single-city question, so the model declines. The eval set has the same blind "
        "spot; it was found in the live demo.",
    )
    meth = [
        rate(summary(RUNS[k]), "turn_success", "methodology")
        for k in (BASE, "Qwen2.5-3B + LoRA, data v1", FINAL)
    ]
    card(
        s,
        L,
        Inches(1.5),
        Inches(5.9),
        Inches(4.8),
        "Fixed: methodology questions",
        f"chose search_knowledge: base {meth[0]:.0f}% → LoRA data v1 {meth[1]:.0f}% → "
        f"data v2 {meth[2]:.0f}%\n\n"
        "Data v1 had no search_knowledge examples, so the model learned never to use the "
        "tool.\n\nData v2 added 180 of them. (Answers not yet scored.)",
    )
    card(
        s,
        Inches(6.8),
        Inches(1.5),
        Inches(5.9),
        Inches(4.8),
        "Not fixed: metric switch after a ranking",
        '"Rank Colorado cities by ZHVI growth in 2025" → "What about rent?"\n→ unsupported\n\n'
        "All 50 metric-switch follow-ups in training follow a single-city question; the eval "
        "set has the same gap.\n\nFound in the live demo; explicit phrasing works.",
    )

    # 13. Lessons
    s = d.slide(
        "Lessons learned", "Pick two or three of these to talk about; the rest are in the docs."
    )
    text_box(
        s,
        L,
        Inches(1.4),
        W,
        Inches(5.6),
        [
            "• Constrained decoding needs a small grammar: the full schema hung TGI; a "
            "structure-only copy plus Pydantic afterwards works",
            "• The validator is also the best data filter: synthetic examples are kept only if "
            "they run correctly on the real data",
            "• Eval gold data has bugs too: four gold plans contradicted the city/state policy "
            "(fixed in v1.1, v1 kept frozen)",
            '• Each training round exposed a data gap (no search examples, "City, ST"-only '
            "follow-ups); coverage beats more epochs",
            "• Deterministic data needs a total sort order: DuckDB row order differed between "
            "laptop and Studio",
            "• Deploying found what tests didn't: a missing Docker plugin, a role without "
            "Session Manager rights",
        ],
        size=19,
    )

    # 14. Future work
    s = d.slide(
        "Future work",
        "Close with the limits honestly, then the next steps. Point to the repo and the docs.",
    )
    text_box(
        s,
        L,
        Inches(1.4),
        Inches(7),
        Inches(5.4),
        [
            "• Training data for metric switches after rankings and for replies to "
            "clarifications (both untested now)",
            "• Metro and ZIP-level series; more operations (correlation, comparisons to a "
            "baseline)",
            "• HTTPS and per-user auth for a public deployment",
            "• Hybrid retrieval if the methodology corpus grows",
        ],
        size=20,
    )
    card(
        s,
        Inches(8.2),
        Inches(1.6),
        Inches(4.5),
        Inches(3.4),
        "Docs",
        "README · architecture · model\nsampling · evaluation · API\ndeployment runbooks\n\n"
        "github.com/weimiao67/llm-class-final",
    )

    path = OUT / "housing-analyst.pptx"
    d.save(path)
    return path


if __name__ == "__main__":
    print(build())
