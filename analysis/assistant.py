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
check_answer), configuration helpers reading the environment and .env
(ANTHROPIC_API_KEY, ASSISTANT_MODEL, ASSISTANT_FREE_TEXT), and ask(), which
sends one question to the model and returns an AssistantReply: a checked
answer, one of the fixed texts in assistant_text, or a fallback. ask() never
raises for an API failure, so the page that calls it never breaks.

Spec: docs/superpowers/specs/2026-10-10-county-ai-assistant-design.md
Plan: docs/superpowers/plans/2026-10-10-county-ai-assistant.md
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import anthropic
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
# -- A blank with the "$" the model may type in front of it
_SLOT_WITH_DOLLAR_RE = re.compile(r"(\$?)\[\[([a-z0-9_]+)\.([a-z0-9_]+)\]\]")
_CENSUS_RE = re.compile(r"(?:U\.?S\.? )?Census Bureau")
# -- Blanks whose value is a verb phrase ("differs from", "is flagged",
# -- "meets"), so "is" written before them doubles the verb
_PHRASE_FIELDS = ("vs_state", "nchs_flag", "hud_median_rule")
_BLANK_GRAMMAR_RE = re.compile(
    r"\b(?:is|are|was|were|be|been)\s+\[\[[a-z0-9_]+\.(?:" + "|".join(_PHRASE_FIELDS) + r")\]\]",
    re.IGNORECASE,
)
_RULE_SLOT_RE = re.compile(r"\[\[rule\.[a-z0-9_]+\]\]")
_SENTENCE_START_RE = re.compile(r"(?:[.!?]\s+|\n\s*)$")

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


def _census_naming(s: str) -> str:
    """"U.S. Census Bureau" at the first mention and "Census Bureau" after
    (the project's naming rule), whatever the model wrote."""
    count = 0

    def name(_: re.Match) -> str:
        nonlocal count
        count += 1
        return "U.S. Census Bureau" if count == 1 else "Census Bureau"

    return _CENSUS_RE.sub(name, s)


def render_answer(template: str, sheet: dict) -> str:
    """Fill every blank from the fact sheet, apply the Census Bureau naming
    rule, and escape each `$` for st.markdown (a pair of unescaped `$`
    renders as math). A `$` the model typed in front of a dollar figure is
    dropped, since the figure carries its own. Raises UnknownBlank for a
    blank the fact sheet does not offer."""
    values = slot_values(sheet)

    def fill(m: re.Match) -> str:
        name = f"{m.group(2)}.{m.group(3)}"
        if name not in values:
            raise UnknownBlank(name)
        value = values[name]
        return value if value.startswith("$") else m.group(1) + value

    filled = _census_naming(_SLOT_WITH_DOLLAR_RE.sub(fill, template))
    return _UNESCAPED_DOLLAR_RE.sub(r"\\$", filled)


_RANGE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
_AND_OVER_RE = re.compile(r"(\d+)(?:\+| and over| and older)")
_PERCENT_RE = re.compile(r"(\d+)%")
_DOLLAR_AMOUNT_RE = re.compile(r"\$(\d[\d,]*\d)(?![\d,]*[kK])")
_UNDER_AGE_RE = re.compile(r"\bunder (\d+)(?!\S*\$)", re.IGNORECASE)


def _literal(phrase: str) -> str:
    """A fixed phrase as a pattern that cannot match inside a longer word or
    number: "under 5" never matches inside "under 50"."""
    head = r"(?<![\w$])" if re.match(r"[\w$]", phrase) else ""
    tail = r"(?![\w%])" if re.search(r"[\w%]$", phrase) else ""
    return head + re.escape(phrase) + tail


def _definitional_patterns(s: str) -> set[str]:
    """Patterns for the numbers that define a measure (an age range, a poverty
    or rent threshold, an income bracket), each allowed only inside the
    wording that gives it that meaning: "aged 5 to 17", "age 25 and over",
    "below 200% of the poverty line", "30% or more of income", "earning
    under $25,000". A definitional number on its own ("30%", "$25,000",
    "5-17") stays a stray number, since the model could otherwise present it
    as a measured figure."""
    age = r"(?<![\w$])(?:age[sd]?|adults|residents|people|children)\s+"
    out: set[str] = set()
    for a, b in _RANGE_RE.findall(s):
        span = rf"{a}\s*(?:-|–|to)\s*{b}(?![\w%])"
        out |= {age + span, rf"(?<![\w$]){span}[\s-]+years?\b"}
    for a in _AND_OVER_RE.findall(s):
        out.add(age + rf"{a}\s*(?:\+|and over|and older|or older)")
    for a in _UNDER_AGE_RE.findall(s):
        out |= {rf"(?<![\w$])(?:age[sd]?|children)\s+under\s+(?:age\s+)?{a}(?![\w%])",
                rf"(?<![\w$])under\s+(?:age\s+)?{a}\s+years?\b"}
    for a in _PERCENT_RE.findall(s):
        out |= {rf"(?<![\w$]){a}%\s+of\s+(?:the\s+)?(?:federal\s+)?poverty(?:\s+(?:line|level|threshold))?\b",
                rf"(?<![\w$]){a}%\s+or\s+more\s+of\s+(?:their\s+|household\s+)?income\b"}
    amounts = [m.replace(",", "") for m in _DOLLAR_AMOUNT_RE.findall(s)]
    if amounts:
        money = [rf"\$(?:{int(x):,}|{x})(?![\d,]*\d)" for x in amounts]
        span = money[0] if len(money) == 1 else rf"{money[0]}\s*(?:-|–|to|and)\s*{money[1]}"
        lead = (r"(?<![\w$])(?:earning|earn|earns|with\s+(?:household\s+)?incomes?|incomes?)\s+"
                r"(?:(?:of|under|below|less\s+than|from|between|over|above|at\s+least)\s+)?")
        out.add(lead + span + r"(?:\+|\s+or\s+more)?")
    return out


def _allowed_patterns(sheet: dict) -> list[str]:
    """Patterns for the text with digits the model may type: the fixed
    phrases in assistant_text.ALLOWED_PHRASES, each measure's label and rate
    label as whole phrases, and each measure's definitional numbers in their
    defining wording (from its label, rate label and registry key). Longest
    first, so a long phrase is removed before a shorter one inside it."""
    literals = set(text.ALLOWED_PHRASES)
    patterns: set[str] = set()
    for m in sheet["measures"].values():
        literals.update(p for p in (m.get("label"), m.get("rate_label")) if p)
        for s in (m.get("label"), m.get("rate_label"), m.get("key")):
            if s:
                patterns |= _definitional_patterns(s.replace("\\$", "$"))
    return [_literal(p) for p in sorted(literals, key=len, reverse=True)] + sorted(patterns, key=len, reverse=True)


def _has_number(s: str) -> bool:
    """Digits, spelled-out numbers, or fraction characters such as "⅓"."""
    return bool(re.search(r"\d", s) or _NUMBER_WORD_RE.search(s)
                or any(unicodedata.category(ch) == "No" for ch in s))


def check_answer(reply: Reply, sheet: dict) -> str | None:
    """Checks 4 to 6 of the spec, in order. Returns the first failed check's
    code, or None when the reply may be shown.

    no_grounding  -- empty answer; measures or terms not in the fact sheet or
                     glossary; or neither a measure nor a term named
    unknown_blank -- a blank the fact sheet does not offer, or a malformed one
    stray_number  -- a digit, number word or fraction left once blanks and
                     allowed phrases are removed; a number that defines a
                     measure is allowed only inside its defining wording
    advice_wording -- a banned verdict or advice phrase
    blank_grammar -- "is" or "are" before a blank that is already a verb
                     phrase ("is differs from")
    rule_placement -- a rule blank that does not start its own sentence; the
                     rule sentence names its source, so a lead-in repeats it
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
    for pattern in _allowed_patterns(sheet):
        bare = re.sub(pattern, " ", bare, flags=re.IGNORECASE)
    if _has_number(bare):
        return "stray_number"

    lowered = prose.lower()
    if any(p in lowered for p in text.BANNED_PHRASES):
        return "advice_wording"

    if _BLANK_GRAMMAR_RE.search(answer):
        return "blank_grammar"
    for m in _RULE_SLOT_RE.finditer(answer):
        before = answer[:m.start()]
        if before.strip() and not _SENTENCE_START_RE.search(before):
            return "rule_placement"
    return None


# -- Configuration ------------------------------------------------------------

def is_configured() -> bool:
    """Whether a credential is present (environment or the repo's .env)."""
    load_dotenv(REPO_ROOT / ".env")
    # -- .env.example's placeholder, copied unchanged, is not a credential
    real = lambda name: (os.environ.get(name) or "").strip() not in ("", "your_key_here")  # noqa: E731
    return real("ANTHROPIC_API_KEY") or real("ANTHROPIC_AUTH_TOKEN")


def model_name() -> str:
    return os.environ.get("ASSISTANT_MODEL") or DEFAULT_MODEL


def free_text_enabled() -> bool:
    """False when ASSISTANT_FREE_TEXT is "0": buttons only, no question box."""
    return os.environ.get("ASSISTANT_FREE_TEXT", "1").strip() != "0"


# -- The model call -----------------------------------------------------------

_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class AssistantReply:
    """What the panel shows for one question.

    status   -- "answer" (checked and filled), "out_of_scope" or
                "not_in_dashboard" (a fixed redirect), "blocked" (too long,
                or failed the checks twice), "unavailable" (refusal, cut-off
                reply or API error)
    text     -- what to show; already $-escaped for st.markdown
    template -- the model's text with blanks, kept as conversation memory;
                None unless status is "answer"
    """

    status: Literal["answer", "out_of_scope", "not_in_dashboard", "blocked", "unavailable"]
    text: str
    template: str | None = None
    failed_check: str | None = None
    attempts: int = 0
    usage: dict | None = None
    checks_failed: tuple[str, ...] = ()  # every failed check, in order, including a retry that then passed
    failed_templates: tuple[str, ...] = ()  # the model's text for each failed attempt; never shown


def make_client():
    """An Anthropic client, or None when no credential is configured."""
    if not is_configured():
        return None
    return anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS)


def _text_block(s: str) -> dict:
    return {"type": "text", "text": s}


def _messages(sheet: dict, on_screen: list[str], history: list[tuple[str, str]],
              question: str) -> list[dict]:
    """Fact sheet first (cached), then up to HISTORY_EXCHANGES earlier
    exchanges, then this question with the cards on screen. The question is
    wrapped in <question> tags and never passed through blank filling."""
    sheet_block = {"type": "text", "text": "FACT SHEET\n" + sheet_for_model(sheet),
                   "cache_control": {"type": "ephemeral"}}
    current = "Cards on screen: " + ", ".join(on_screen) + "\n<question>" + question + "</question>"
    turns = [("<question>" + q + "</question>", a) for q, a in history[-HISTORY_EXCHANGES:]]
    out: list[dict] = []
    for q, a in turns:
        out.append({"role": "user", "content": [_text_block(q)]})
        out.append({"role": "assistant", "content": [_text_block(a)]})
    out.append({"role": "user", "content": [_text_block(current)]})
    out[0]["content"].insert(0, sheet_block)
    return out


def _add_usage(total: dict, usage) -> None:
    for k in _USAGE_KEYS:
        total[k] += getattr(usage, k, 0) or 0


def ask(client, sheet: dict, on_screen: list[str], history: list[tuple[str, str]],
        question: str) -> AssistantReply:
    """One question in, one checked reply out, with at most one retry.

    on_screen holds measure ids; history holds (question_sent, template)
    pairs for earlier answers, oldest first."""
    # -- The limit is for typed questions; the ready-made prompts are ours and longer
    if len(question) > MAX_QUESTION_CHARS and question not in {p.prompt for p in text.PRESETS}:
        return AssistantReply("blocked", text.TOO_LONG)

    messages = _messages(sheet, on_screen, history, question)
    usage = dict.fromkeys(_USAGE_KEYS, 0)
    failed: list[str] = []
    failed_texts: list[str] = []

    def done(status, shown, attempt, **kw) -> AssistantReply:
        return AssistantReply(status, shown, attempts=attempt, usage=usage,
                              checks_failed=tuple(failed), failed_templates=tuple(failed_texts), **kw)

    for attempt in (1, 2):
        try:
            response = client.messages.parse(
                model=model_name(),
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": text.SYSTEM_PROMPT,
                         "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                output_config={"effort": "low"},
                output_format=Reply,
            )
        except anthropic.AuthenticationError:
            return done("unavailable", text.UNAVAILABLE, attempt)
        except anthropic.RateLimitError:
            return done("unavailable", text.UNAVAILABLE, attempt)
        except anthropic.APIStatusError:
            return done("unavailable", text.UNAVAILABLE, attempt)
        except anthropic.APIConnectionError:
            return done("unavailable", text.UNAVAILABLE, attempt)
        except pydantic.ValidationError:
            # -- the reply did not match the four-field schema
            return done("unavailable", text.UNAVAILABLE, attempt)

        _add_usage(usage, getattr(response, "usage", None))
        if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
            return done("unavailable", text.UNAVAILABLE, attempt)

        reply: Reply = response.parsed_output
        if reply.kind == "out_of_scope":
            return done("out_of_scope", text.REDIRECT_OUT_OF_SCOPE, attempt)
        if reply.kind == "not_in_dashboard":
            return done("not_in_dashboard", text.REDIRECT_NOT_IN_DASHBOARD, attempt)

        check = check_answer(reply, sheet)
        if check is None:
            return done("answer", render_answer(reply.answer, sheet), attempt, template=reply.answer)
        failed.append(check)
        failed_texts.append(reply.answer)
        messages = messages + [
            {"role": "assistant", "content": [_text_block(reply.model_dump_json())]},
            {"role": "user", "content": [_text_block(
                f"Your reply failed this check: {check}. Write it again and follow the rules.")]},
        ]
    return done("blocked", text.FALLBACK, 2, failed_check=failed[-1])
