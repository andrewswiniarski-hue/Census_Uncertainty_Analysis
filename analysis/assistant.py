"""Engine for the dashboard's "Ask about this county" assistant.

What it does
------------
Turns one question about one county into one checked, plain-language answer.
The model never types a number: it writes named blanks such as
[[median_household_income.estimate]], and this module fills each blank from
the county's fact sheet with the exact string the dashboard card shows. Before
anything is shown, the reply must pass the checks in check_answer (grounded,
every blank resolves, no stray digits or spelled numbers, no advice wording).

What it needs
-------------
- A fact sheet: the dictionary Streamlit/app_US_v7.py builds with
  _county_fact_sheet (shape in the plan, Task 2). Only its display strings
  ("blanks") are sent to the model; raw numbers ("values") never are.
- All wording from analysis/assistant_text.py.
- No Streamlit. Nothing here imports it, so every function is testable alone.

What it produces
----------------
Pure functions (measure_id, slot_values, sheet_for_model, render_answer,
check_answer) and configuration helpers reading the environment and .env
(ANTHROPIC_API_KEY, ASSISTANT_MODEL, ASSISTANT_FREE_TEXT).

Spec: docs/superpowers/specs/2026-10-10-county-ai-assistant-design.md
Plan: docs/superpowers/plans/2026-10-10-county-ai-assistant.md
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

import pydantic
from dotenv import load_dotenv

from analysis import assistant_text as text

REPO_ROOT = Path(__file__).resolve().parents[1]

MAX_QUESTION_CHARS = 400
MAX_QUESTIONS_PER_SESSION = 20
MAX_TOKENS = 4000
HISTORY_EXCHANGES = 6
DEFAULT_MODEL = "claude-haiku-5-5"

SLOT_RE = re.compile(r"\[\[([a-z0-9_]+)\.([a-z0-9_]+)\]\]")
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(text.NUMBER_WORDS) + r")s?\b", re.IGNORECASE
)
_UNESCAPED_DOLLAR_RE = re.compile(r"(?<!\\)\$")

# -- Fields of a measure that go to the model (never "values" or "key")
_MODEL_FIELDS = ("label", "topic", "table", "status", "unit", "rate_label", "blanks")


class Reply(pydantic.BaseModel):
    """The four fields the model must return (structured output schema)."""

    kind: Literal["answer", "out_of_scope", "not_in_dashboard"]
    answer: str
    measures_used: list[str]
    terms_explained: list[str]


class UnknownBlank(KeyError):
    """A blank in the model's text that the fact sheet does not offer."""


def measure_id(registry_key: str) -> str:
    """Blank-name form of a measure registry key: lower case, every run of
    other characters becomes one underscore, none at the ends.
    "Poverty: 5-17" -> "poverty_5_17"."""
    return re.sub(r"[^a-z0-9]+", "_", registry_key.lower()).strip("_")


def _available_rules() -> list[str]:
    return ["esri", "nchs"] + (["hud"] if text.HUD_RULE_VERIFIED else [])


def slot_values(sheet: dict) -> dict[str, str]:
    """Every blank the model may write, mapped to its display string."""
    out = {f"county.{k}": v for k, v in sheet["county"]["blanks"].items()}
    for mid, m in sheet["measures"].items():
        out.update({f"{mid}.{k}": v for k, v in m["blanks"].items()})
    out.update({f"rule.{n}": text.RULES[n] for n in _available_rules()})
    return out


def sheet_for_model(sheet: dict) -> str:
    """The fact sheet as the model sees it: display strings only, as JSON with
    sorted keys, so the same county gives byte-identical text (prompt cache)."""
    payload = {
        "county": {"blanks": sheet["county"]["blanks"]},
        "measures": {
            mid: {f: m.get(f) for f in _MODEL_FIELDS}
            for mid, m in sheet["measures"].items()
        },
        "rules": _available_rules(),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def render_answer(template: str, sheet: dict) -> str:
    """Fill every blank from the fact sheet and escape each `$` for
    st.markdown (a pair of unescaped `$` renders as math). Raises
    UnknownBlank for a blank the fact sheet does not offer."""
    values = slot_values(sheet)

    def fill(m: re.Match) -> str:
        name = f"{m.group(1)}.{m.group(2)}"
        if name not in values:
            raise UnknownBlank(name)
        return values[name]

    return _UNESCAPED_DOLLAR_RE.sub(r"\\$", SLOT_RE.sub(fill, template))


def _allowed_phrases(sheet: dict) -> list[str]:
    phrases = set(text.ALLOWED_PHRASES)
    for m in sheet["measures"].values():
        phrases.update(p for p in (m.get("label"), m.get("rate_label")) if p)
    return sorted(phrases, key=len, reverse=True)


def check_answer(reply: Reply, sheet: dict) -> str | None:
    """Checks 4 to 6 of the spec, in order. Returns the first failed check's
    code, or None when the reply may be shown.

    no_grounding  -- empty answer; measures or terms not in the fact sheet or
                     glossary; or neither a measure nor a term named
    unknown_blank -- a blank the fact sheet does not offer, or a malformed one
    stray_number  -- a digit or number word left once blanks and allowed
                     phrases are removed
    advice_wording -- a banned verdict or advice phrase
    """
    answer = reply.answer
    if (
        not answer.strip()
        or not set(reply.measures_used) <= set(sheet["measures"])
        or not set(reply.terms_explained) <= set(text.GLOSSARY)
        or not (reply.measures_used or reply.terms_explained)
    ):
        return "no_grounding"

    values = slot_values(sheet)
    if any(f"{a}.{b}" not in values for a, b in SLOT_RE.findall(answer)):
        return "unknown_blank"
    prose = SLOT_RE.sub(" ", answer)
    if "[[" in prose or "]]" in prose:
        return "unknown_blank"

    bare = prose
    for phrase in _allowed_phrases(sheet):
        bare = re.sub(re.escape(phrase), " ", bare, flags=re.IGNORECASE)
    if re.search(r"\d", bare) or _NUMBER_WORD_RE.search(bare):
        return "stray_number"

    lowered = prose.lower()
    if any(p in lowered for p in text.BANNED_PHRASES):
        return "advice_wording"
    return None


# -- Configuration ------------------------------------------------------------

def is_configured() -> bool:
    """Whether a credential is present (environment or the repo's .env)."""
    load_dotenv(REPO_ROOT / ".env")
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def model_name() -> str:
    return os.environ.get("ASSISTANT_MODEL") or DEFAULT_MODEL


def free_text_enabled() -> bool:
    """False when ASSISTANT_FREE_TEXT is "0": buttons only, no question box."""
    return os.environ.get("ASSISTANT_FREE_TEXT", "1").strip() != "0"
