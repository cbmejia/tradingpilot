Look at the attached chart screenshot. This is meant to be a **{timeframe}**
timeframe chart for **{symbol}**, shown for broader trend context only —
you are not analyzing a specific trade setup here, and you have not been
shown any trade parameters.

## What to do

1. **Read the timeframe label actually visible on the chart itself** — the
   timeframe selector shown in the chart's own toolbar or title (e.g. a
   button or label reading "4h", "1D", "1W"). Report exactly what you see
   there, as plain text. This is used only to confirm the correct chart
   was actually captured — it is not a trading signal, and you should not
   guess at it or assume it matches the `{timeframe}` mentioned above if
   the chart itself shows something different.
2. Classify the overall trend direction visible on this chart, and its
   strength, using only the fixed categories below.

- **confirmation_visible_timeframe** — the timeframe label exactly as it
  appears on the chart (plain text, whatever you actually see — do not
  normalize "4h" to "4H" or guess if it's not legible).
- **confirmation_trend_direction** — one of: `UP`, `DOWN`, `SIDEWAYS`,
  `UNCLEAR`
- **confirmation_trend_quality** — how strong is that trend? One of:
  `STRONG`, `MODERATE`, `WEAK`, `UNCLEAR`

Respond with **only** this JSON object — no other text, no markdown code
fence, no trailing commentary:

{{
  "confirmation_visible_timeframe": "...",
  "confirmation_trend_direction": "UP" | "DOWN" | "SIDEWAYS" | "UNCLEAR",
  "confirmation_trend_quality": "STRONG" | "MODERATE" | "WEAK" | "UNCLEAR"
}}

Do not include a score, a rating, a percentage, a probability, a confidence
value, a likelihood, or odds of any kind, under any field name. Every
category field must be exactly one of its listed options — never a number,
never a word outside that list. Do not recommend placing a trade or phrase
anything as an instruction to buy or sell.
