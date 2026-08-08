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
  "context_risk": "LOW" | "MODERATE" | "ELEVATED" | "UNCLEAR"
}}

Do not include a score, a rating, a percentage, or any other number that
represents confidence or quality — that is computed separately, by code,
never by you. Every category field must be exactly one of its listed
options — never a number, never a word outside that list. Do not
recommend placing a trade or phrase anything as an instruction to buy or
sell — describe only what is observable. Keep every prose field to a few
sentences at most — the category fields above are what get scored, not
how much you write.
