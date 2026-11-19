#!/usr/bin/env python3
"""quick-start importer: bring what a person already uses elsewhere into this Agate project.

    python3 .agents/skills/quick-start/import.py scan <path>... [--out plan.json]
    python3 .agents/skills/quick-start/import.py apply [plan.json] [--yes]

`scan` classifies files, folders and zips (Claude memory export, agents, skills, CLAUDE.md/AGENTS.md, notes, data,
connector hints) and writes a plan. `apply` is a dry run unless `--yes`; it does only the safe parts (documents,
skills, memory entries, the "This project" section, personal style) and prints what is left to do with the person
(connectors, API keys). Secrets are never copied: .env files are skipped and key-looking lines are dropped.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

TEXT_EXT = {".md", ".markdown", ".txt", ".json", ".yml", ".yaml"}
DATA_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".pdf", ".docx", ".pptx", ".odt", ".ods", ".png", ".jpg", ".jpeg"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".agate"}
INSTRUCTION_NAMES = {"claude.md", "agents.md", "gemini.md", "system_prompt.md", "system-prompt.md", "instructions.md"}
SECRET_LINE = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{20,}|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}|tvly-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{30,}|"
    r"github_pat_[A-Za-z0-9_]{40,}|xox[abprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{30,}|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|^\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S+)")
ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9_]{2,}_(?:API_KEY|TOKEN|SECRET|KEY|ACCESS_TOKEN)\b")
MCP_URL = re.compile(r"https?://[^\s)\"'>]*mcp[^\s)\"'>]*", re.I)
TOOLS = ["Figma", "ClickUp", "Notion", "Linear", "Amplitude", "Slack", "Jira", "Confluence", "Miro", "Intercom",
         "Pendo", "Fireflies", "HubSpot", "Google Drive", "Google Sheets", "Google Docs", "monday", "Asana",
         "BigQuery", "Postgres", "Mixpanel", "Airtable", "GitHub", "Sentry", "Zendesk", "Stripe"]
PERSONA_HEADINGS = re.compile(r"(identi|role\b|rol\b|tono|tone|car[aá]cter|character|personal|idioma|language|"
                              r"qui[eé]n eres|who you are)", re.I)
PERSONAL = re.compile(r"\b(i prefer|i like|i want you|my style|prefers|likes to|me gusta|prefiero|quiero que|"
                      r"no me gusta|pregúntame|preguntame|ask me)\b", re.I)


# ---------------------------------------------------------------- helpers

def find_root(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / ".agate" / "agate.py").is_file() and (p / "AGENTS.md").is_file():
            return p
    return None


def slugify(text: str, limit: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:limit].rstrip("-") or "item")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def strip_secrets(text: str) -> tuple[str, int]:
    kept, dropped = [], 0
    for line in text.splitlines():
        if SECRET_LINE.search(line):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if text.endswith("\n") else ""), dropped


def frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip().strip("\"'")
    return meta, text[end + 4:].lstrip("\n")


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------- scan

def memory_facts(path: Path, text: str) -> list[str] | None:
    """Facts if this looks like a Claude (or similar) memory export, else None."""
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except ValueError:
            return None
        items = data.get("memories") or data.get("memory") if isinstance(data, dict) else data
        if isinstance(items, list):
            out = []
            for it in items:
                if isinstance(it, str):
                    out.append(it)
                elif isinstance(it, dict):
                    v = it.get("content") or it.get("text") or it.get("memory")
                    if isinstance(v, str):
                        out.append(v)
            return [f.strip() for f in out if f.strip()] or None
        return None
    head = (path.name + " " + text[:400]).lower()
    if "memor" not in head:
        return None
    facts = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", ln).strip() for ln in text.splitlines()
             if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+\S", ln)]
    return facts or None


def classify_file(path: Path, rel: str) -> dict:
    name, ext = path.name.lower(), path.suffix.lower()
    if name.startswith(".env") or name in {"credentials.json", "secrets.json"}:
        return {"kind": "secret-file", "source": rel}
    if ext in DATA_EXT:
        return {"kind": "data", "source": rel}
    if ext not in TEXT_EXT:
        return {"kind": "other", "source": rel}
    text = read_text(path)
    if name in INSTRUCTION_NAMES:
        return {"kind": "instructions", "source": rel}
    facts = memory_facts(path, text)
    if facts:
        return {"kind": "memory-export", "source": rel, "facts": len(facts)}
    meta, body = frontmatter(text)
    if meta.get("name") and meta.get("description") and ext in {".md", ".markdown"}:
        if name == "skill.md":
            return {"kind": "skill", "source": rel}
        return {"kind": "agent", "source": rel, "name": meta["name"]}
    return {"kind": "notes", "source": rel}


def walk(paths: list[Path], tmp: Path):
    """Yield (path, rel, is_skill_dir) for every input, expanding folders and zips."""
    for p in paths:
        p = p.expanduser()
        if p.is_file() and p.suffix.lower() == ".zip":
            dest = tmp / slugify(p.stem)
            with zipfile.ZipFile(p) as z:
                for member in z.namelist():
                    target = (dest / member).resolve()
                    if str(target).startswith(str(dest.resolve())):
                        z.extract(member, dest)
            yield from walk([dest], tmp)
        elif p.is_dir():
            if (p / "SKILL.md").is_file():
                yield p, p.name, True
                continue
            for child in sorted(p.iterdir()):
                if child.name in SKIP_DIRS:
                    continue
                yield from walk([child], tmp)
        elif p.is_file():
            yield p, p.name, False


def destination(item: dict) -> tuple[str, str]:
    kind, base = item["kind"], slugify(Path(item["source"]).stem)
    if kind == "memory-export":
        return "memory/", "memory add (team facts → shared; personal ones → your style in preferences)"
    if kind == "agent":
        return f".agents/skills/{slugify(item.get('name') or base)}/SKILL.md", \
            "convert to a skill (flows kept, persona trimmed); check `agate.py search` for an existing one first"
    if kind == "skill":
        return f".agents/skills/{slugify(item['name'])}/", "copy as a project skill (or use an equivalent from the library)"
    if kind == "instructions":
        return "AGENTS.md › This project", "append the project context (never inside the agate block)"
    if kind in {"notes", "data"}:
        return f"documents/imported/{Path(item['source']).name}", "copy + line in documents/INDEX.md"
    if kind == "secret-file":
        return "-", "skipped (possible secrets; set keys with env-manager or `agate.py env set`)"
    return "-", "skipped (unknown type)"


def scan(paths: list[Path]) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="agate-import-"))
    items, connectors, env_vars, mcp_urls = [], set(), set(), set()
    for path, rel, is_skill in walk(paths, tmp):
        if is_skill:
            meta, _ = frontmatter(read_text(path / "SKILL.md"))
            item = {"kind": "skill", "source": rel, "name": meta.get("name") or rel, "path": str(path)}
        else:
            item = classify_file(path, rel)
            item["path"] = str(path)
        files = list(path.rglob("*")) if path.is_dir() else [path]
        for f in files:
            if f.is_file() and f.suffix.lower() in TEXT_EXT and not f.name.lower().startswith(".env"):
                text = read_text(f)
                connectors |= {t for t in TOOLS if re.search(r"\b" + re.escape(t) + r"\b", text, re.I)}
                env_vars |= set(ENV_NAME.findall(text))
                mcp_urls |= set(MCP_URL.findall(text))
        item["id"] = len(items) + 1
        item["dest"], item["action"] = destination(item)
        item["auto"] = item["kind"] in {"memory-export", "agent", "skill", "instructions", "notes", "data"}
        items.append(item)
    return {"created": _dt.date.today().isoformat(), "tmp": str(tmp), "items": items,
            "connectors": sorted(connectors), "mcp_urls": sorted(mcp_urls)[:10], "env_vars": sorted(env_vars)}


def render_plan(plan: dict) -> list[str]:
    lines = [f"Import plan ({len(plan['items'])} items):"]
    shown = plan["items"][:20]
    for it in shown:
        extra = f" · {it['facts']} facts" if it.get("facts") else ""
        lines.append(f"{it['id']:>2}. [{it['kind']}] {it['source']}{extra} → {it['dest']}")
    if len(plan["items"]) > len(shown):
        lines.append(f"    +{len(plan['items']) - len(shown)} more (see the plan file)")
    if plan["connectors"]:
        lines.append("Connectors mentioned: " + ", ".join(plan["connectors"][:12]) +
                     " → offer them with .agate/core/guides/mcp-add.md (official first, ask the person)")
    if plan["env_vars"]:
        lines.append("API key names seen: " + ", ".join(plan["env_vars"][:8]) +
                     " → `agate.py env add NAME --where … --for …` (names only, never values)")
    skipped = [i for i in plan["items"] if i["kind"] == "secret-file"]
    if skipped:
        lines.append(f"Skipped {len(skipped)} file(s) that may hold secrets.")
    lines.append("Next: show this to the person in plain words; with their ok run `import.py apply --yes`.")
    return lines[:30]


# ---------------------------------------------------------------- apply

def agent_to_skill(text: str, source: str) -> str:
    meta, body = frontmatter(text)
    name = slugify(meta.get("name", Path(source).stem))
    description = meta.get("description", "").strip() or f"Imported from {source}."
    sections = re.split(r"(?m)^(?=#{1,3} )", body)
    perspective, kept = "", []
    for sec in sections:
        heading = sec.splitlines()[0] if sec.strip() else ""
        if heading.startswith("#") and PERSONA_HEADINGS.search(heading):
            if not perspective:
                prose = " ".join(l.strip() for l in sec.splitlines()[1:] if l.strip() and not l.startswith("#"))
                sentences = re.split(r"(?<=[.!?])\s+", prose)
                perspective = " ".join(sentences[:2])[:300]
            continue
        if sec.strip():
            kept.append(sec.rstrip())
    out = ["---", f"name: {name}", f"description: {yaml_quote(description[:400])}", "---", "",
           f"# {meta.get('name', name)}", "",
           f"<!-- imported from {source} on {_dt.date.today().isoformat()}; persona sections trimmed "
           "(flows, criteria and formats kept). Review it with the person. -->", ""]
    if perspective:
        out += ["## Perspective", perspective, ""]
    out += ["\n\n".join(kept), ""]
    return "\n".join(out)


def run_cli(root: Path, *args: str, stdin: str | None = None) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(root / ".agate" / "agate.py"), *args], cwd=root, input=stdin,
                       capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def load_prefs(root: Path):
    path = root / ".agate" / "core" / "lib" / "prefs.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("agate_prefs", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - optional helper
        return None
    return mod


def copy_text(src: Path, dest: Path) -> int:
    clean, dropped = strip_secrets(read_text(src))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(clean, encoding="utf-8")
    return dropped


def apply(plan: dict, root: Path, yes: bool) -> list[str]:
    done, left, dropped = [], [], 0
    docs_index = root / "documents" / "INDEX.md"
    for it in plan["items"]:
        src, kind = Path(it.get("path", "")), it["kind"]
        if not it.get("auto") or not src.exists():
            continue
        if not yes:
            done.append(f"would: {it['action']} → {it['dest']}")
            continue
        if kind in {"notes", "data"}:
            dest = root / "documents" / "imported" / src.name
            if src.suffix.lower() in TEXT_EXT:
                dropped += copy_text(src, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            rel = dest.relative_to(root).as_posix()
            line = f"- [{src.name}]({rel.replace('documents/', '', 1)}) — imported from {it['source']}\n"
            current = read_text(docs_index)
            if rel.replace("documents/", "", 1) not in current:
                docs_index.parent.mkdir(parents=True, exist_ok=True)
                with docs_index.open("a", encoding="utf-8") as f:
                    f.write(("" if current.endswith("\n") or not current else "\n") + line)
            done.append(f"documents: {rel}")
        elif kind == "agent":
            text, n = strip_secrets(read_text(src))
            dropped += n
            dest = root / it["dest"]
            if dest.exists():
                left.append(f"skill {dest.parent.name} already exists: compare by hand")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(agent_to_skill(text, it["source"]), encoding="utf-8")
            done.append(f"skill: {dest.relative_to(root).as_posix()} (review the trimmed persona)")
        elif kind == "skill":
            dest = root / ".agents" / "skills" / slugify(it.get("name") or src.name)
            if dest.exists():
                left.append(f"skill {dest.name} already exists: compare by hand")
                continue
            for f in src.rglob("*"):
                if f.is_dir() or f.name.lower().startswith(".env") or any(p in SKIP_DIRS for p in f.parts):
                    continue
                target = dest / f.relative_to(src)
                if f.suffix.lower() in TEXT_EXT or f.suffix.lower() in {".py", ".sh", ".js"}:
                    dropped += copy_text(f, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
            done.append(f"skill: .agents/skills/{dest.name}/ (it may need `agate.py doctor`)")
        elif kind == "instructions":
            text, n = strip_secrets(read_text(src))
            dropped += n
            body = "\n".join(text.splitlines()[:80]).strip()
            agents = root / "AGENTS.md"
            content = read_text(agents)
            block = f"\n\n### Imported from {it['source']}\n<!-- condense with the person -->\n{body}\n"
            if "## This project" in content and f"### Imported from {it['source']}" not in content:
                agents.write_text(content.rstrip("\n") + block, encoding="utf-8")
                done.append(f"AGENTS.md › This project: added context from {it['source']} (condense it)")
        elif kind == "memory-export":
            facts = memory_facts(src, read_text(src)) or []
            personal = [f for f in facts if PERSONAL.search(f)]
            team = [f for f in facts if f not in personal]
            made = 0
            for fact in team[:50]:
                clean, n = strip_secrets(fact)
                dropped += n
                if not clean.strip():
                    continue
                name = slugify(" ".join(clean.split()[:6]), 40)
                code, _ = run_cli(root, "memory", "add", name, "--description", clean.strip()[:120],
                                  "--type", "imported", "--scope", "shared", "--body", "-", stdin=clean)
                made += code == 0
            if len(team) > 50:
                rest = root / "documents" / "imported" / f"{slugify(src.stem)}-rest.md"
                rest.parent.mkdir(parents=True, exist_ok=True)
                rest.write_text("\n".join(f"- {f}" for f in team[50:]) + "\n", encoding="utf-8")
                done.append(f"documents: {rest.relative_to(root).as_posix()} ({len(team) - 50} more facts)")
            done.append(f"memory: {made} team facts from {it['source']}")
            if personal:
                prefs = load_prefs(root)
                style = "; ".join(p.strip().rstrip(".") for p in personal[:3])[:240]
                notes = root / "memory" / "local" / "imported-preferences.md"
                notes.parent.mkdir(parents=True, exist_ok=True)
                notes.write_text("\n".join(f"- {strip_secrets(p)[0].strip()}" for p in personal) + "\n",
                                 encoding="utf-8")
                if prefs and hasattr(prefs, "update"):
                    prefs.update(root, Path("memory/local/preferences.yml"), style=style,
                                 notes="memory/local/imported-preferences.md")
                    done.append("your style: memory/local/preferences.yml (+ notes)")
                else:
                    left.append("save the person's style from memory/local/imported-preferences.md")
    for tool in plan.get("connectors", []):
        left.append(f"connector {tool}: ask whether to connect it (.agate/core/guides/mcp-add.md)")
    for var in plan.get("env_vars", []):
        left.append(f"key {var}: `agate.py env add {var} --where … --for …`, value via env-manager/terminal")
    out = done[:20]
    if dropped:
        out.append(f"Skipped {dropped} line(s) that looked like secrets.")
    if left:
        out.append("Left to do with the person:")
        out += [f"- {x}" for x in left[:12]]
    if not yes:
        out.append("Dry run: nothing changed. Rerun with --yes after the person's ok.")
    return out


# ---------------------------------------------------------------- CLI

def default_plan_path(root: Path | None) -> Path:
    base = (root / "memory" / "local" / ".cache") if root else Path.cwd()
    return base / "quick-start-import-plan.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import what a person already uses into this Agate project.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="classify files/folders/zips and write a plan")
    s.add_argument("paths", nargs="+")
    s.add_argument("--out", help="plan file (default memory/local/.cache/quick-start-import-plan.json)")
    a = sub.add_parser("apply", help="apply a plan (dry run unless --yes)")
    a.add_argument("plan", nargs="?")
    a.add_argument("--yes", action="store_true")
    a.add_argument("--root", help="project root (default: found from the current folder)")
    args = ap.parse_args(argv)
    root = find_root(Path.cwd())
    if args.cmd == "scan":
        plan = scan([Path(p) for p in args.paths])
        out = Path(args.out) if args.out else default_plan_path(root)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n".join(render_plan(plan)))
        print(f"Plan saved: {out}")
        return 0
    root = Path(args.root).resolve() if args.root else root
    if not root:
        print("Not inside an Agate project (no .agate/agate.py found).")
        return 2
    plan_path = Path(args.plan) if args.plan else default_plan_path(root)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"No plan at {plan_path}: run `import.py scan <paths>` first.")
        return 2
    print("\n".join(apply(plan, root, args.yes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
