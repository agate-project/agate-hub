# Product extension (`extensions/product`)

Agate expansion for product work: discovery, data memos, critical idea reviews, tickets, measurement plans, proposal
canvases, design system and editorial PDF documents.

**Status: design.** It has no skills yet. The specification is in the workspace's `specs/product-expansion.md`.

It is agnostic: it contains nothing from any company. Each business's context (market, competitors, formats, design
system) goes in the project that installs it. Like the base, everything here is in English; the agent replies in each
person's language.

## Install (once it has content)
From the root of an Agate project (base ≥ 0.3.0):
```
python3 .agate/agate.py add product
```
