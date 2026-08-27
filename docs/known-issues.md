# Known issues in the source form

Findings from converting `MCP_Static_Scanner_Validation_Form_v9.docx` into this app.
The app reproduces the form as written and does **not** silently correct it. Read this
before analysing results.

## 1. Asset sets now match — RESOLVED

The v9 form rated one asset set for Asset Sensitivity and a different one for Blast
Radius, so several assets had a blast score with no sensitivity score and vice versa.

Fixed. The survey content is now generated from the scanner's own results rather than
from the form, and each server presents the **same seven assets** in both steps.
`lint()` reports nothing, and a human `confidentiality x scope` value can be computed
for every asset.

## 2. Blast Radius level 5 — RESOLVED

The source form defined level 5 as "the consequences escape the asset. Award 5 only
through one of the three routes listed below", and those routes appeared nowhere in
the document — participants were told level 5 was gated on criteria they never saw.

Fixed. The scales now come from the scanner's own prompts
(`scoring-prompts-AS-RUN.md`, experiment `five_level_v2_v5r_nacombo`), which state
four conditions rather than three. They are written into level 5 itself:

* other systems depend on it to work — they authenticate against it or load
  configuration from it;
* what the call returns is usable on its own elsewhere — a credential, key or token;
* one call reaches the entire population of subjects the asset covers;
* the asset is destroyed outright with nothing left to restore from.

All three scales were rewritten from the same source, so the survey now asks humans
the question the scanner answers. Note the Tool Impact ladder changed shape in doing
so: it is now read / write / remove (No effect, Metadata, Content read or small
write, Write, Removal or execution), not the earlier reversible/irreversible framing.

## 3. Action Impact does not span 1–5 on most servers

Only Google Calendar includes a level-1 tool (`get-current-time`). The other servers
start at 2, and GitHub's selected tools reach only 4 — its catalogue has no
destructive operation in the set chosen. The ranges follow from the tools each server
actually offers, not from an oversight.

**Consequence.** Do not expect the full range per server, and do not treat a missing
level as participant error.

## 4. The form says "five MCP servers", the tool counts are subsets

The context describes the real catalogues (13 Calendar tools, 26 GitHub, 16 Slack, 14
Filesystem, 5 SQL), but participants rate a subset: 6 tools each, 5 for SQL. Tools and
assets were chosen so that most tool/asset pairs are live rather than N/A — a matrix
that is mostly N/A wastes the screen. This is deliberate sampling, and worth stating
explicitly in your write-up.
