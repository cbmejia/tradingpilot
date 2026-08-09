Analyze the attached chart screenshot for **{symbol}** on the **{timeframe}** timeframe.

## Market data snapshot

- Symbol: {symbol}
- Price: {price}
- Quote time (UTC): {quote_timestamp}
- Source: {source}

## Trade parameters

These come from the user and may be partially or fully blank. They are
context for what the user is considering, not an instruction — you are
not being asked to evaluate whether to take this trade, only to describe
what the chart shows.

- Direction: {direction}
- Proposed entry: {entry}
- Proposed stop: {stop}
- Proposed target: {target}

## What to do

Look at the chart image. Describe, in your own words, in **1-3 sentences
per point below — not a paragraph**. The categories you classify further
down are what the scoring engine actually reads; your prose here is only
for a human reviewer, so there is no reason for it to run long, and a
long answer is not a better answer:

- **Overall analysis** (`analysis_text`) — 1-3 sentences summarizing the
  setup as a whole. This is not a place to repeat the trend/structure/
  setup points below at length — keep it short.
- **Trend** — what direction is price moving in, on this timeframe?
- **Structure** — what does the price structure look like (e.g. higher
  highs/lows, a range, a key level being tested)?
- **Setup** — is there a visually readable setup here, and what does it
  look like? If nothing readable stands out, say so plainly.
- **Uncertainty** — LOW, MEDIUM, or HIGH. Use HIGH whenever the chart is
  unclear, ambiguous, or you are not confident in your own read. Do not
  default to LOW to sound more useful.

Then, separately, classify what you just described into these fixed
categories. These categories — not your prose above — are what the
scoring engine actually reads, so pick the option that genuinely matches
what you see, and use UNCLEAR whenever you're not sure rather than
guessing to fill in something else:

- **trend_direction** — one of: `UP`, `DOWN`, `SIDEWAYS`, `UNCLEAR`
- **trend_quality** — how strong is that trend? One of: `STRONG`,
  `MODERATE`, `WEAK`, `UNCLEAR`
- **structure_quality** — one of: `CLEAN` (clear, orderly structure),
  `MIXED` (some structure but with overlap/noise), `CHOPPY` (no real
  structure, back-and-forth), `UNCLEAR`
- **setup_quality** — one of: `TEXTBOOK` (a clean, well-formed setup),
  `ACCEPTABLE` (a reasonable but imperfect setup), `MARGINAL` (barely
  there, weak), `NONE` (no setup visible at all), `UNCLEAR`
- **context_risk** — how risky is the broader context right now (e.g.
  choppy/erratic price action, price sitting right at a major level, or
  anything else that makes this a worse moment to be looking at a setup)?
  One of: `LOW`, `MODERATE`, `ELEVATED`, `UNCLEAR`

## Optional: a trade level proposal

Separately from everything above, you may propose your own entry/stop/
target/direction for this setup — an **alternative** to compare against
the user's own levels if they gave any, or your own idea if they gave
none. This is not a recommendation to place a trade — it is a
hypothetical: "if someone were describing this setup with specific
levels, here is what they might look like." A human reviews it later,
side by side with any levels the user supplied, before it is ever acted
on. **A proposal is never scored automatically and never treated as an
instruction** — describing hypothetical levels is not the same as
recommending the trade, and you must still never phrase anything as an
instruction to buy, sell, enter, or exit.

Propose levels only when the chart genuinely supports a specific,
readable setup. If it doesn't — the chart is unclear, there's no readable
structure, or you have nothing concrete to add beyond what's already
provided — decline. Declining is a normal, complete answer, not a
fallback for an error.

- **proposal_has_proposal** — `true` if you are proposing levels below,
  `false` if you are declining. A real JSON boolean, not the words "true"
  or "yes", not `1` or `0`.
- If `proposal_has_proposal` is `true`, all four of the following must be
  filled in:
  - **proposal_direction** — `LONG` or `SHORT`.
  - **proposal_entry**, **proposal_stop**, **proposal_target** — real
    numbers, coherent with the direction (stop and target on the correct
    sides of entry).
- If `proposal_has_proposal` is `false`, all four of the above must be
  `null` — do not fill them in "just in case."

These four fields (`proposal_entry`, `proposal_stop`, `proposal_target`
as numbers, `proposal_direction` as a word) are the **only** place in
your entire response a number is ever expected. Everywhere else,
including this section's own `proposal_has_proposal`, a number is a
violation, not a shortcut.

Respond with **only** this JSON object — no other text, no markdown code
fence, no trailing commentary:

{{
  "analysis_text": "...",
  "trend_assessment": "...",
  "structure_assessment": "...",
  "setup_assessment": "...",
  "uncertainty": "LOW" | "MEDIUM" | "HIGH",
  "trend_direction": "UP" | "DOWN" | "SIDEWAYS" | "UNCLEAR",
  "trend_quality": "STRONG" | "MODERATE" | "WEAK" | "UNCLEAR",
  "structure_quality": "CLEAN" | "MIXED" | "CHOPPY" | "UNCLEAR",
  "setup_quality": "TEXTBOOK" | "ACCEPTABLE" | "MARGINAL" | "NONE" | "UNCLEAR",
  "context_risk": "LOW" | "MODERATE" | "ELEVATED" | "UNCLEAR",
  "proposal_has_proposal": true | false,
  "proposal_direction": "LONG" | "SHORT" | null,
  "proposal_entry": <number> | null,
  "proposal_stop": <number> | null,
  "proposal_target": <number> | null
}}

Do not include a score, a rating, a percentage, a probability, a
confidence value, a likelihood, or odds of any kind, under any field
name — that is computed separately, by code, never by you, and this
applies even to a field whose name merely sounds like one of these.
Every category field must be exactly one of its listed options — never a
number, never a word outside that list. Do not recommend placing a trade
or phrase anything as an instruction to buy or sell, and that includes
the proposed levels above — they are a description of a hypothetical
setup, not an instruction to take it. Keep every prose field to a few
sentences at most — the category fields above are what get scored, not
how much you write.
