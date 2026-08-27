# Editing the survey

All survey content lives in `survey_config.json`. The app renders whatever is there
and contains no question text of its own.

## Changing wording, tools or assets

Edit `survey_config.json` directly, then run the tests:

```bash
python -m pytest tests -q
```

`tests/test_config.py` checks the file still loads and still matches the expected
shape. If you intentionally changed the number of tools or assets, update
`test_server_shapes_match_the_source_form` to match.

## Structure

```json
{
  "title": "...",
  "subtitle": "...",
  "intro": "...",
  "consent": "...",
  "scales": { "impact": [], "sensitivity": [], "blast": [] },
  "step_prompts": { "impact": "...", "sensitivity": "...", "blast": "..." },
  "servers": [
    {
      "key": "calendar",
      "title": "Google Calendar",
      "enabled": true,
      "scenario": "...",
      "mcp_context": "...",
      "tools":  [{ "name": "...", "desc": "..." }],
      "assets": [{ "name": "...", "desc": "..." }],
      "blast":  {
        "tools":  ["..."],
        "assets": [{ "name": "...", "desc": "..." }],
        "live":   ["<asset>|<tool>"]
      }
    }
  ]
}
```

* `key` is a stable id used in CSV column names.
* `enabled: false` removes the server from the survey and from the CSV.
* `scenario` is the **organisational** context: what this deployment means to CBG.
  Shown on Asset Sensitivity and Blast Radius.
* `mcp_context` describes the **server itself** — what it exposes, independent of any
  organisation. Shown on Tool Impact and Blast Radius.

The split is deliberate. Tool Impact asks what a tool does, so the organisation is a
distraction; Asset Sensitivity asks what the data is worth to this organisation;
Blast Radius is the reach of a tool over an asset and needs both.
* `tools` drives Step 1, `assets` drives Step 2, and `blast` drives the Step 3 matrix
  (`blast.tools` are the rows, `blast.assets` the columns).
* `blast.live` lists the pairs the tool actually acts on, taken from the scanner's own
  `blast_radius` map (a non-null entry means live). Every other cell renders read-only
  as N/A. A tool with no live pair should be left out of `blast.tools` entirely.

Each scale must have exactly the levels 1–5, in order. Blast matrix tools must all
appear in that server's `tools` list. Names must not contain `__`, which separates the
parts of a CSV column name.

## How many servers each participant sees

`servers_per_participant` at the top of `survey_config.json` controls this. Set it to
the number of servers in the config to go back to showing everyone all of them.

Assignment is balanced, not uniformly random: the least-covered servers are handed out
first, ties broken at random, so coverage stays within one of even at any point. See
`survey/assignment.py`.

## Running a subset of servers

Set `"enabled": false` on any server. Disabled servers disappear from the wizard and
contribute no CSV columns. To pilot with Google Calendar alone, disable the other four.

## Renaming things after data collection has started

Avoid it. Tool, asset and server names are CSV column names, so renaming one splits
your data across two columns. Add a new entry instead, or remap during analysis.

## Regenerating from the Word form

The initial config was generated from `MCP_Static_Scanner_Validation_Form_v9.docx` by
walking its nested tables. That generator is not part of this repository, because the
form is a working document containing an appendix of expected values that must never
reach participants. If you regenerate, extract **participant-facing sections only** —
`tests/test_config.py` asserts that no researcher key material is present.
