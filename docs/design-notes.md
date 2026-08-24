# Design notes

Why the rating screens look the way they do. Sources are listed at the end.

## Layout

Each rating step is a single table: a row per tool or asset, five columns for the
1–5 scale. Row label and description sit on the left, the circles on the right,
aligned under a numbered header.

Alignment is structural, not cosmetic: the header and every row are built from the
same `st.columns([label, 1, 1, 1, 1, 1])` spec, so each rating control sits in its
own Streamlit column and lines up with its header by construction.

An earlier version used a horizontal `st.radio` per row and tried to spread its
options with CSS. That was fragile — the options are laid out by the widget's own
styled-components at their natural width, and overriding it means matching internal
DOM that can change between Streamlit releases. It repeatedly rendered the circles
bunched at the left. Buttons in columns have no such dependency.

## Accessibility

Matrix questions are the classic accessibility trap — a true HTML `<table>` of
radios is hard to navigate with a screen reader, and the usual advice is to fall
back to a series of individual questions.

No layout table is involved: the grid is made of ordinary containers, and each
rating control is a real focusable button carrying its level name and definition as
a tooltip (`1 — Liveness — The system only says "I am here" …`).

**Trade-off, stated plainly:** these are buttons, not a native radio group, so a
screen reader announces five buttons in a row rather than "1 of 5 selected". That is
weaker than a real `radiogroup`. It was accepted because the radio-based version
could not be aligned reliably, and an unreadable grid fails sighted and low-vision
users too. If the study needs to be run with screen-reader participants, replace
each row with a vertical `st.radio` — one question per screen — which is the
fallback the accessibility guidance recommends anyway.

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
