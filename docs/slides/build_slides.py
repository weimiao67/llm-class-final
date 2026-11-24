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
        "Hi, I'm <your name>. My project is a housing-market analyst you can ask questions in "
        "plain English. The twist: a small model I fine-tuned decides what to compute, but it "
        "never does the math itself. Code does. I'll show how it works, how much fine-tuning "
        "helped, and then a live demo running on AWS.",
    )
    text_box(s, L, Inches(2.3), W, Inches(1.2), ["Housing Market AI Analyst"], size=44, bold=True)
    text_box(
        s,
        L,
        Inches(3.6),
        W,
        Inches(1.2),
        [
            "Ask about home values and rents in plain English. A small fine-tuned model plans "
            "the analysis, and code does the math."
        ],
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
        "Here's the whole project on one slide, grouped the way the project is graded. On the "
        "left is the model work: I compared three small models, fine-tuned the best one, and "
        "built a 200-question test set to measure it. In the middle is how a question gets "
        "answered, including how I sample from the model, and the API on top. On the right "
        "is the AWS deployment, the docs, and the demo. The rest of the talk walks through "
        "each part.",
    )
    text_box(
        s,
        L,
        Inches(1.25),
        W,
        Inches(1.0),
        [
            "Answers questions about U.S. city home values and rents (Zillow's ZHVI and "
            "ZORI). A fine-tuned 3B model plans each answer; code checks it and does the math."
        ],
        size=18,
        color="ink2",
    )
    glance = [
        (
            "Model · LoRA · evaluation",
            "• Compared Llama-3.2-3B, Phi-4-mini, and Qwen2.5-3B, then fine-tuned Qwen with "
            "LoRA on SageMaker\n"
            "• Generated 3,000 training examples and kept only the ones that ran correctly on "
            "the real data\n"
            f"• Built a 200-question test set with correct answers: accuracy went from "
            f"{ex_base:.0f}% to {ex_final:.0f}%",
        ),
        (
            "Inference pipeline · sampling · API",
            "• Question → plan → checked against the data → SQL → a short answer\n"
            "• Plans: greedy decoding, held to a JSON schema. Answers: sampled at "
            "temperature 0.3, then every number is checked\n"
            "• Methodology questions search a small set of notes; a REST API serves it all",
        ),
        (
            "Deployment · docs · demo",
            "• The model runs on a SageMaker endpoint; the app (API + web UI) runs in Docker "
            "on EC2\n"
            f"• A README and {n_docs} docs, including step-by-step runbooks for AWS\n"
            "• Automated tests on every change, and a live demo (with a backup recording)",
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
        ["Code, docs, test results, and this deck: github.com/weimiao67/llm-class-final"],
        size=14,
        color="ink2",
    )

    # 3. Problem
    s = d.slide(
        "The problem",
        "Take a simple question: how did rents change in Denver over three years? To answer it "
        "you need the right dataset, the right Denver, the right months, a calculation, and a "
        "note about what the index actually measures. If you ask a chatbot, it'll give you a "
        "confident number it made up. If you let a model write SQL, you have to trust "
        "whatever query it writes. So my question was: can a small model, trained for just "
        "this job, plan these analyses reliably?",
    )
    text_box(
        s,
        L,
        Inches(1.4),
        Inches(7.2),
        Inches(5),
        [
            '"How did rents change in Denver over three years?"',
            "• Pick the right data: Zillow's rent index, smoothed and seasonally adjusted",
            "• Pick the right city: some names exist in several counties of the same state",
            "• Pick the months, compute the change, and flag any missing data",
            "• Explain what the index actually measures",
            "Ask a chatbot and it makes up a number. Let a model write SQL and you have to "
            "trust its query.",
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

    # 4. Approach
    s = d.slide(
        "How it works: the model plans, code computes",
        "Let's follow one question left to right. The model's only job here is to fill in a "
        "structured plan: which metric, which cities, which months, which calculation. Then "
        "plain code takes over. It checks the plan against the data, turns it into SQL, and "
        "runs it. The model comes back at the end to write a sentence or two about the "
        "result, and a last check makes sure every number in that sentence really came from "
        "the result.",
    )
    steps = [
        ("Question", "in plain English"),
        ("Planner", "fine-tuned model\nwrites a plan"),
        ("Validator", "checks cities and\nmonths in the data"),
        ("SQL + DuckDB", "runs the query\nsafely"),
        ("Answer writer", "1–2 sentences\nabout the result"),
        ("Number check", "every number must\ncome from the result"),
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
            "Blue boxes are the model. Everything else is ordinary code that behaves the same "
            "every time.",
            "• A city name that matches several places? It asks which one instead of guessing",
            "• A question about how the indexes work? It searches my notes on Zillow's methods",
            "• A forecast, financial advice, or raw SQL? It says no and offers what it can do",
        ],
        size=18,
    )

    # 5. Trust boundary
    inj = final["families"]["injection"]["turn_success"]
    s = d.slide(
        "What the model can and can't do",
        "This is why I trust the numbers. The model can only fill in a plan, ask a question "
        "back, or say no. It never writes SQL or touches the database. And it can't put a "
        "number in front of you that isn't in the result: if it tries, the answer is "
        "rewritten, and as a last resort, code writes it. One thing is trained rather than "
        "enforced: ignoring instructions hidden inside a question. It got 9 of the 10 test "
        "cases right.",
    )
    card(
        s,
        L,
        Inches(1.5),
        Inches(5.9),
        Inches(4.6),
        "The model can",
        "Pick a tool: analyze data, search the notes, or reply\n\n"
        "Fill in a plan: metric, cities or state, months, calculation\n\n"
        "Ask which city you meant, or decline a question\n\n"
        "Write the sentence that goes with the result",
    )
    card(
        s,
        Inches(6.8),
        Inches(1.5),
        Inches(5.9),
        Inches(4.6),
        "The model can't (code enforces it)",
        "Write SQL or code, or touch the database\n\n"
        "Show you a number that isn't in the result (every answer is checked)\n\n"
        "Guess a state you didn't mention (the validator asks instead)\n\n"
        "Trained, not enforced: ignoring instructions hidden in a question "
        f"({inj['hits']} of {inj['n']} tests)",
    )

    # 6. Model
    s = d.slide(
        "Picking a model, then fine-tuning it",
        "Before training anything, I gave three small models the same prompt and the same test "
        "set. Phi-4-mini didn't even run on the serving stack I used. Qwen beat Llama by about "
        "24 points, so I fine-tuned Qwen. The base model's mistakes were very consistent, "
        "which is exactly what fine-tuning is good at fixing. I used LoRA, trained only on "
        "the plan it should output, for one pass over the data. That took about 37 minutes "
        "on a single GPU.",
    )
    llama = rate(summary(RUNS["Llama-3.2-3B (base)"]), "execution_accuracy")
    text_box(
        s,
        L,
        Inches(1.4),
        Inches(6.2),
        Inches(5),
        [
            "Same prompt, same 200 test questions (accuracy):",
            f"• Llama-3.2-3B: {llama:.1f}%",
            "• Phi-4-mini: wouldn't run on the serving stack (TGI 3.3.6)",
            f"• Qwen2.5-3B: {ex_base:.1f}%  → the one I fine-tuned",
            "Its mistakes were consistent: it guessed lists of cities for statewide "
            "questions, and it often declined the wrong way.",
        ],
        size=18,
    )
    card(
        s,
        Inches(7.2),
        Inches(1.5),
        Inches(5.5),
        Inches(4.4),
        "The fine-tune",
        "LoRA: rank 16, alpha 32, on all attention and MLP layers\n\n"
        "Learns only the plan it should output\n\n"
        "One pass over 2,661 examples · learning rate 2e-4\n\n"
        "One A10G GPU (ml.g5.xlarge) · 37 minutes · 8.5 GB\n\n"
        "Adapter merged into the model for serving",
    )

    # 7. Training data
    s = d.slide(
        "Training data: generated, then checked",
        "I didn't have real training data, so I generated it. A small grammar writes each "
        "question and its correct plan from the same pieces, so the pair is right by "
        "construction. Then I ran every example through the same validator and query code "
        "the app uses, and threw out anything that didn't work on the real data, plus "
        "anything too close to a test question. The app's own code turned out to be the "
        "best quality filter.",
    )
    funnel = [
        ("Question grammar", "40 templates,\n7 kinds of question"),
        ("Run on real data", "keep it only if\nthe plan works"),
        ("Keep tests separate", "no test cities, plans,\nor look-alike questions"),
        ("3,000 examples", "2,661 train / 339 dev\n317 thrown out"),
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
            "The mix: single-city questions, statewide questions, follow-ups, ambiguous "
            "cities, things to decline, fixing a rejected plan, and methodology questions",
            "• The dev set uses sentence patterns the model never saw in training",
            "• No training question is a near copy of a test question (every one checked)",
            "• Rebuilding gives exactly the same data, verified with checksums",
        ],
        size=18,
    )

    # 8. Sampling
    s = d.slide(
        "Sampling: exact plans, checked answers",
        "The model gets called twice per question, and I decode the two calls differently. "
        "For the plan, I want the single most likely answer every time, so I use greedy "
        "decoding, and the server is only allowed to produce output that fits my JSON schema. "
        "For the sentence at the end, a little variety reads better, so I sample at "
        "temperature 0.3. Since sampling can slip in a wrong number, every number is checked "
        "against the result, and a failed answer gets a second try, then a template.",
    )
    card(
        s,
        L,
        Inches(1.5),
        Inches(5.9),
        Inches(2.4),
        "Plans: greedy, held to a JSON schema",
        "The server can only produce output that fits the schema\n"
        "A full schema made the server hang; a slimmer one works\n"
        "The schema also forces cities or a state, and real state codes",
    )
    card(
        s,
        Inches(6.8),
        Inches(1.5),
        Inches(5.9),
        Inches(2.4),
        "Answers: temperature 0.3, top-p 0.9",
        "Every number has to appear in the result\n"
        "If not: try again greedily, then fall back to a template",
    )
    text_box(
        s,
        L,
        Inches(4.2),
        W,
        Inches(2.8),
        [
            "What actually happened in testing (fine-tuned model):",
            "• 9 out of 10 first answers passed the number check (139 of 155)",
            "• The rest mostly had math slips, like 33,821.90 where the result said 3,382.19",
            "• Bad plans that needed a retry: 25 before fine-tuning, 0 after",
            "• After fine-tuning, the schema barely matters (89.3% with it, 90.1% without): "
            "the model has learned the format",
        ],
        size=17,
    )

    # 9. Results
    s = d.slide(
        "Results: fine-tuning closed most of the gap",
        f"The main number is accuracy: for each test question I run the model's plan and the "
        f"correct plan, and check that the results match. That's the same idea text-to-SQL "
        f"benchmarks use. The base model got {ex_base:.0f}% right; after fine-tuning it gets "
        f"{ex_final:.0f}%. Counting every kind of question, including the ones it should ask "
        f"about or decline, it goes from {ts_base:.0f}% to {ts_final:.0f}%. And every first "
        f"output is now valid JSON.",
    )
    s.shapes.add_picture(str(IMG / "chart_accuracy.png"), L, Inches(1.3), width=Inches(7.6))
    card(
        s,
        Inches(8.6),
        Inches(1.5),
        Inches(4.1),
        Inches(1.4),
        f"{ts_final:.1f}%",
        f"of all 200 test questions handled right (base: {ts_base:.1f}%)",
        fill="blue",
    )
    card(
        s,
        Inches(8.6),
        Inches(3.1),
        Inches(4.1),
        Inches(1.4),
        "100%",
        f"valid output on the first try (base: {rate(base, 'envelope_valid'):.0f}%)",
    )
    p50, p95 = final["overall"]["latency_ms_p50"] / 1000, final["overall"]["latency_ms_p95"] / 1000
    card(
        s,
        Inches(8.6),
        Inches(4.7),
        Inches(4.1),
        Inches(1.4),
        f"{p50:.1f} s",
        f"for a typical question; 95% finish within {p95:.1f} s",
    )

    # 10. By family
    s = d.slide(
        "Where fine-tuning helped",
        "The biggest jumps are exactly where the base model kept failing: statewide questions, "
        "and knowing when and how to decline. Single-city questions went from 83% to 100%. "
        "One category slipped a little, highest-and-lowest-month questions, from 18 to 17 out "
        "of 20. And a note on methodology: the 100% there means it chose to search my notes; "
        "the answers themselves haven't been scored yet.",
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
                f"• {label}: {rate(base, 'turn_success', f):.0f}% → "
                f"{rate(final, 'turn_success', f):.0f}%"
                for f, label in (
                    ("multi_city", "Several cities"),
                    ("aggregate", "Statewide averages"),
                    ("boundary", "Declining correctly"),
                    ("injection", "Ignoring injected text"),
                )
            ),
            "One small drop: highest/lowest month, 90% → 85%.",
            "Methodology = chose to search the notes; answers not scored yet.",
        ],
        size=17,
    )

    # 11. Deployment
    s = d.slide(
        "Running it on AWS",
        "Here's how it's deployed. The model sits on a SageMaker endpoint. The app, the API "
        "and the web UI, runs in two Docker containers on one small EC2 instance, which costs "
        "about 70 cents a day. Only my IP address can reach it, and it needs an API key. The "
        "instance's permissions are narrow: it can call this one model endpoint and read its "
        "own data, nothing else. The GPU endpoint is the expensive part, so I delete it after "
        "every session.",
    )
    boxes = [
        ("Browser or curl", "my IP address only\nAPI key required"),
        ("EC2 t3.small", "Docker: web UI → API\nDuckDB over Parquet files"),
        ("SageMaker endpoint", "TGI model server\nQwen2.5-3B + LoRA\nGPU: g5 (or g6 fallback)"),
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
            "• The web UI calls the same API you'd call with curl",
            "• Locked down: one allowed IP, an API key, and minimal AWS permissions",
            "• Cost: about $0.70 a day for the app; the GPU endpoint (~$1.50/hour) only runs "
            "when needed",
            "• Every step is scripted and written up as a runbook in the repo",
        ],
        size=18,
    )

    # 12. Demo
    s = d.slide(
        "Live demo",
        "Let's try it. I'll ask these in order, in one conversation. For each one I'll show "
        "the answer, then the evidence tab: the plan the model wrote, the SQL that ran, which "
        "city it matched, and a trace of every step. Then I'll call the API directly with "
        "curl. If the network gives me trouble, I have a recording.",
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
            "7. The same question through the API, with curl",
        ],
        size=19,
    )
    image_or_placeholder(s, IMG / "ui_rank.png", Inches(7.2), Inches(1.4), width=Inches(5.6))

    # 13. One fixed, one not
    s = d.slide(
        "One problem fine-tuning fixed, and one it didn't",
        "First, a fix. My first round of training data had no examples of searching the "
        "methodology notes, so the model stopped searching altogether: it dropped from 73% to "
        "27%. Adding 180 examples brought it to 100%. Now one it didn't fix. If you rank "
        "Colorado cities by home value and then just say 'What about rent?', the model says "
        "it can't do that. The cause is the same kind of gap: in training, switching to rent "
        "only ever came after a single-city question. My test set had the same blind spot; "
        "I only found it in the live demo.",
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
        "Fixed: questions about methodology",
        f"Chose to search the notes: {meth[0]:.0f}% before → {meth[1]:.0f}% after round 1 → "
        f"{meth[2]:.0f}% after round 2\n\n"
        "Round 1 had no search examples, so the model learned to never search.\n\n"
        "Round 2 added 180 of them. (The answers themselves aren't scored yet.)",
    )
    card(
        s,
        Inches(6.8),
        Inches(1.5),
        Inches(5.9),
        Inches(4.8),
        "Not fixed: switching to rent after a ranking",
        '"Rank Colorado cities by ZHVI growth in 2025" → "What about rent?"\n'
        "→ the model says it can't\n\n"
        "In training, switching to rent only ever followed a single-city question. My test "
        "set had the same gap.\n\n"
        'I found it in the live demo. Spelling it out works: "What about rent growth for '
        'the same cities and year?"',
    )

    # 14. Lessons
    s = d.slide(
        "What I learned",
        "I'll pick two or three of these. The one I'd stress: every round of training "
        "exposed a gap in the data, and fixing the data helped far more than training longer.",
    )
    text_box(
        s,
        L,
        Inches(1.4),
        W,
        Inches(5.6),
        [
            "• Keep the grammar small. My full JSON schema made the model server hang; a "
            "slimmer version plus a check afterwards works fine",
            "• Your own app is the best data filter: keep a generated example only if it runs "
            "correctly on the real data",
            "• Test sets have bugs too. Four expected answers in mine contradicted my own "
            "rules, so I published a corrected version and kept the original frozen",
            "• Each training round exposed a data gap. A second epoch didn't help; better "
            "coverage did",
            "• Make generated data reproducible. Row order differed between my laptop and "
            "SageMaker until I sorted everything explicitly",
            "• Deploying finds what tests don't: a missing Docker plugin, and a permission I "
            "forgot",
        ],
        size=19,
    )

    # 15. Future work
    s = d.slide(
        "What's next",
        "To wrap up: here's what I'd do next, starting with the two gaps I just showed you. "
        "Everything is in the repo: the code, the docs, and every test result. Thanks! "
        "Happy to take questions.",
    )
    text_box(
        s,
        L,
        Inches(1.4),
        Inches(7),
        Inches(5.4),
        [
            "• Teach the two things it can't do yet: switching to rent after a ranking, and "
            "following up after it asks which city",
            "• Score the methodology answers, not just the choice to search",
            "• Add metro and ZIP-code data, and more calculations",
            "• HTTPS and real user accounts, if it were ever public",
        ],
        size=20,
    )
    card(
        s,
        Inches(8.2),
        Inches(1.6),
        Inches(4.5),
        Inches(3.4),
        "Read more",
        "README · how it works · the model\nsampling · test results · API\nAWS runbooks\n\n"
        "github.com/weimiao67/llm-class-final",
    )

    path = OUT / "housing-analyst.pptx"
    d.save(path)
    return path


if __name__ == "__main__":
    print(build())
