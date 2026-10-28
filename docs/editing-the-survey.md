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

When running locally, restart `streamlit run` (or choose **Clear cache** from the app's
menu) to see a config edit: the loaded config is cached. On Streamlit Cloud a push to
`main` is enough.

## Structure

```json
{
  "title": "...",
  "subtitle": "...",
  "intro": "...",
  "consent": "...",
  "servers_per_participant": 2,
  "show_timer": true,
  "scales": { "impact": [], "sensitivity": [], "blast": [] },
  "scale_labels": { "impact": "Action Impact", "...": "..." },
  "step_prompts": { "impact": "...", "sensitivity": "...", "blast": "...", "inputs": "..." },
  "input_choices": { "changes": "...", "no_change": "..." },
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
      },
      "inputs": [{ "tool": "...", "tool_desc": "...", "input": "...", "desc": "...",
                   "examples": ["...", "..."] }]
    }
  ]
}
```

Each scale level is `{"value", "label", "meaning", "examples"}`. `scale_labels` holds
the step names participants see; the code falls back to built-in names for any that
are missing.

* `key` is a stable id used in CSV column names.
* `enabled: false` removes the server from the survey and from the CSV.
* `scenario` is the **organisational** context: what this deployment means to the
  server's organisation (Aurora Airways, Helios Grid, Vireo Bio or CBG).
  Shown on Asset Sensitivity, Blast Radius and Inputs.
* `mcp_context` describes the **server itself** — what it exposes, independent of any
  organisation. Shown on Tool Impact, Blast Radius and Inputs.

The split is deliberate. Tool Impact asks what a tool does, so the organisation is a
distraction; Asset Sensitivity asks what the data is worth to this organisation;
Blast Radius is the reach of a tool over an asset and needs both.
* `tools` drives Step 1, `assets` drives Step 2, and `blast` drives the Step 3 matrix
  (`blast.tools` are the rows, `blast.assets` the columns).
* `inputs` (optional) drives Step 4, Inputs That Change the Risk. Each entry is
  `{"tool", "tool_desc", "input", "desc", "examples": [two values]}`; entries of the same
  tool are shown on one card. A server without `inputs` skips the step. The step needs
  `step_prompts.inputs` and `input_choices` (`{"changes": "...", "no_change": "..."}`,
  the two answer labels; "Not sure" is always added). Never put the scanner's own
  answer in an entry: the config is participant-facing.
* `show_timer` (top level, default `true`) shows a clock of the time so far on every
  page. The seconds per page are recorded either way.
* The Consequence Scope matrix (`blast`) samples 4 of the server's tools and 4 of its
  assets, chosen so that every pair is live: two tools that read and two that write,
  assets from the least to the most sensitive. The other steps keep all 6 tools and 7
  assets.
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
