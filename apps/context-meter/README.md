# context-meter

A single report page: how much context this project takes in every message and in total, per model family
(Claude, Gemini, OpenAI), with thresholds from `.agate/config.yml`, the heaviest files, a trend over time and what
to do (trim instructions, condense memory, add a search index, move to RAG).

Installed **on demand** (never by default): `python3 .agate/agate.py add app:context-meter`.

```
python3 .agate/apps/context-meter/run.py --open    # build and open (Orca's browser → your browser → remote hint)
python3 .agate/apps/context-meter/run.py --save    # keep it as artifacts/YYYY-MM/YYYY-MM-DD-context-meter.html
python3 .agate/apps/context-meter/run.py --exact   # official counters when credentials exist
```

- Numbers come from `agate.py tokens --json` (one row per provider; never averaged). Skill descriptions are shown as
  their own subtotal of "always loaded".
- Each run adds one point per day to `memory/local/context-history.json`; the trend appears from the second day.
- The report has no secrets (token counts and file paths only). By default it goes to `memory/local/.cache/`.
- On a remote machine it never uses public links: Orca's browser, the `remote-preview` skill, or an SSH
  port-forward.

## Agate Desktop
Mini standalone page for now; Agate Desktop will embed the same report.
