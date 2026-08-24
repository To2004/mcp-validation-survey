# Design notes

Why the rating screens look the way they do. Sources are listed at the end.

## Layout

Each rating step is a single table: a row per tool or asset, five columns for the
1–5 scale. Row label and description sit on the left, the circles on the right,
aligned under a numbered header.

The alignment is done with CSS grid rather than by spacing radio buttons: the
header and every row use `grid-template-columns: repeat(5, 1fr)` across the same
column width, so the circles land under their numbers at any window size. Each
option's own text label is hidden, because the header already names the column.

## Accessibility

Matrix questions are the classic accessibility trap — a true HTML `<table>` of
radios is hard to navigate with a screen reader, and the usual advice is to fall
back to a series of individual questions.

This app gets both: **every row is its own radio group** with its own accessible
label ("Tool Impact rating for get-event"), so assistive technology reads it as an
ordinary question, while CSS arranges the groups into a grid for sighted users. No
layout table is involved.

Other choices from the same guidance:

* **Anchors are labelled.** The header shows `1 — Liveness` and `5 — Irreversible`,
  not a bare 1–5, so the direction of the scale is never ambiguous.
* **Scale direction is consistent** across all three steps: low number = low level.
* **Row counts stay small** (5–7 per step), since long matrices raise cognitive load
  and drop-out.
* **Hit targets are the full cell**, not just the circle, and cells highlight on hover.

## Colour

Low-saturation neutral page (`#eef2f7`) with white cards and a single accent
(`#2563eb`). Zebra striping on alternate rows uses `#f7f9fc` — deliberately faint.
The readability research on zebra striping is mixed: it does not measurably speed
reading, but it slightly improves accuracy and makes wide tables feel easier, and
the consistent advice is to keep the stripe subtle and low-saturation rather than
using strong alternating colours, which can confuse users with colour-vision
deficiencies.

Colour is never the only carrier of meaning: read-only cells say `N/A` in text as
well as being greyed and dashed.

## Sources

* [Accessible Likert Matrix — Ohio State](https://u.osu.edu/cswqualtrics/2024/08/14/accessible-likert-scale-questions/)
* [Designing Accessible Surveys — University of Minnesota](https://it.umn.edu/services-technologies/resources/qualtrics-designing-accessible-surveys)
* [Matrix questions in surveys: when and how to use them — Typeform](https://www.typeform.com/blog/matrix-questions-in-surveys-when-and-how-to-use-them)
* [Matrix Questions: Examples and How to Create Them — IntelliSurvey](https://www.intellisurvey.com/blog/how-to-create-matrix-questions)
* [Zebra Striping: Does it Really Help? — A List Apart](https://alistapart.com/article/zebrastripingdoesithelp/)
* [Zebra Striping: More Data for the Case — A List Apart](https://alistapart.com/article/zebrastripingmoredataforthecase/)
