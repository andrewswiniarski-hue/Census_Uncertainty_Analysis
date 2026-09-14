# Talk Track — "Imputation is invisible to MOE and independent of it"

*Audience: non-statistical. Runtime: 60–90 seconds. Stage directions in italics.*

---

## 1. The two problems + the question (~25 sec)

"A Census number can be shaky in two different ways. One: not enough people were
surveyed, so the estimate comes with an error bar. Two: people who *were* surveyed
skipped questions, and the Bureau filled in guesses — that's imputation, and it's
about **1 in 7** answers statewide. Our question: does the error bar warn you about
the guessing? If it did, one number could flag both problems."

## 2. The graphs (~30 sec)

*Gesture at the panels.*

"Each dot is a New Jersey tract — guessing on the horizontal, error bar size on the
vertical. If error bars detected guessing, the dots would climb to the upper right.
Instead: clouds. There's one trap — small places are worse at both, just for being
small — so we removed the size effect first. Best example is poverty, bottom right:
what looked like a real relationship, minus 0.18, collapsed to zero once size was
accounted for. Same result in all four panels."

## 3. Land it (~25 sec)

*Point to the "~23%" box.*

"So the two problems don't travel together. A tract can have a trustworthy-looking
error bar while a big share of its data is guesses — 23% of the tracts we classified
are exactly that. Check only the error bar and those places look fine when they're
not. That's why our reliability score measures both separately: the data shows one
number can't capture them."

---

## Pocket answers (if asked)

- **"Why is the vertical axis a log scale?"** — Error bars range from tiny to huge;
  the log scale keeps the small ones from being squashed flat at the bottom.
- **"How did you remove the size effect?"** — We calculated how much of each measure
  is explained by tract population, subtracted that part out, and correlated what
  remained.
- **"Why does the poverty panel say 'proxy'?"** — The Census doesn't publish a
  poverty-specific imputation table, so we used the closest published one (the
  family-universe table) as a stand-in, and we label it as such.
- **"Is 1-in-7 guessing bad?"** — It's normal for surveys; the point isn't that
  imputation is scandalous, it's that it's *invisible* if you only look at error bars.
