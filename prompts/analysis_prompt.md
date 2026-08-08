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

Look at the chart image. Describe:

- **Trend** — what direction is price moving in, on this timeframe?
- **Structure** — what does the price structure look like (e.g. higher
  highs/lows, a range, a key level being tested)?
- **Setup** — is there a visually readable setup here, and what does it
  look like? If nothing readable stands out, say so plainly.
- **Uncertainty** — LOW, MEDIUM, or HIGH. Use HIGH whenever the chart is
  unclear, ambiguous, or you are not confident in your own read. Do not
  default to LOW to sound more useful.

Respond with **only** this JSON object — no other text, no markdown code
fence, no trailing commentary:

{{
  "analysis_text": "...",
  "trend_assessment": "...",
  "structure_assessment": "...",
  "setup_assessment": "...",
  "uncertainty": "LOW" | "MEDIUM" | "HIGH"
}}

Do not include a score, a rating, a percentage, or any other number that
represents confidence or quality — that is computed separately, by code,
never by you. Do not recommend placing a trade or phrase anything as an
instruction to buy or sell — describe only what is observable.
