#!/usr/bin/env python3
"""context-meter: a one-page report of how much context this project takes, per model family, and what to do.

  run.py            build the report (memory/local/.cache/) and print a 2-line summary
  run.py --open     also open it (Orca's browser → local browser → remote-preview hint; never public)
  run.py --save     save it as an artifact (artifacts/YYYY-MM/YYYY-MM-DD-context-meter.html)
  run.py --exact    ask the providers' official counters when credentials exist

Numbers come from `agate.py tokens --json`; nothing here reads .env values.
"""

import argparse
import html
import http.server
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import launch  # noqa: E402

DEFAULTS = {"tokens_always_loaded_warn": 3000, "tokens_shared_memory_warn": 30000, "tokens_corpus_index": 100000,
            "tokens_corpus_rag": 300000, "tokens_memory_index_lines": 150}
HISTORY = os.path.join("memory", "local", "context-history.json")
L = {
    "en": {"title": "Project context", "sub": "How much context this project takes in each message and in total, "
           "per model family.", "always": "Always loaded", "always_d": "AGENTS.md, CLAUDE.md, style, skill "
           "descriptions and memory index, in every message", "skills": "of which skill descriptions",
           "shared": "Shared memory", "shared_d": "memory/shared/, read when needed",
           "corpus": "Corpus", "corpus_d": "documents/ + artifacts/", "limit": "warn at {x}",
           "providers": "Per model family", "family": "Family", "tokens": "Tokens", "source": "Source",
           "heavy": "Heaviest files", "recs": "What to do", "none": "Nothing to do: the project is within its budget.",
           "trend": "Over time", "trend_n": "Not enough history yet: one point per day you run it.",
           "est": "Estimates use characters ÷ 3.5 unless calibrated or exact; providers are never averaged.",
           "gen": "Generated {d} by context-meter"},
    "es": {"title": "Contexto del proyecto", "sub": "Cuánto contexto ocupa este proyecto en cada mensaje y en total, "
           "por familia de modelos.", "always": "Siempre cargado", "always_d": "AGENTS.md, CLAUDE.md, estilo, "
           "descripciones de skills e índice de memoria, en cada mensaje", "skills": "de eso, descripciones de skills",
           "shared": "Memoria compartida", "shared_d": "memory/shared/, se lee cuando hace falta",
           "corpus": "Corpus", "corpus_d": "documents/ + artifacts/", "limit": "aviso en {x}",
           "providers": "Por familia de modelos", "family": "Familia", "tokens": "Tokens", "source": "Fuente",
           "heavy": "Archivos más pesados", "recs": "Qué hacer", "none": "Nada que hacer: el proyecto está dentro "
           "de su presupuesto.", "trend": "En el tiempo", "trend_n": "Todavía no hay historial suficiente: un punto "
           "por cada día que lo corras.", "est": "Las estimaciones usan caracteres ÷ 3,5 salvo que estén calibradas o "
           "sean exactas; nunca se promedian proveedores.", "gen": "Generado el {d} por context-meter"},
}


def top(rows):
    return max((r.get("tokens", 0) for r in (rows or {}).values()), default=0)


def skill_descriptions_estimate(root):
    total = 0
    for base in (os.path.join(root, ".agents", "skills"),):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name, "SKILL.md")
            try:
                with open(p, encoding="utf-8") as f:
                    head = f.read(4000)
            except OSError:
                continue
            m = re.search(r"^description:\s*(.+?)(?=^\w[\w-]*:|^---)", head, re.S | re.M)
            total += len((m.group(1) if m else "").encode("utf-8"))
    return int(round(total / 3.5))


def thresholds(root):
    cfg = launch.read_yaml(os.path.join(root, ".agate", "config.yml"))
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        try:
            out[k] = int(str(cfg.get(k, out[k])).replace("_", ""))
        except ValueError:
            pass
    return out


def summarize(report, root):
    g = report.get("groups", {})
    skills = report.get("skill_descriptions")
    if isinstance(skills, dict):
        skills = top(skills) if all(isinstance(v, dict) for v in skills.values()) else skills.get("tokens", 0)
    if not isinstance(skills, int):
        skills = skill_descriptions_estimate(root)
    return {"always": top(g.get("always_loaded")), "shared": top(g.get("shared_memory")),
            "corpus": top(g.get("corpus")), "skills": skills}


def append_history(root, snap, today=None):
    path = os.path.join(root, HISTORY)
    try:
        with open(path, encoding="utf-8") as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = []
    day = today or date.today().isoformat()
    hist = [h for h in hist if h.get("date") != day] + [dict(snap, date=day)]
    hist = hist[-365:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2)
        f.write("\n")
    return hist


def sparkline(values, color, w=260, h=56):
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = w / (len(values) - 1)
    pts = " ".join("%.1f,%.1f" % (i * step, h - 6 - (v - lo) / span * (h - 12)) for i, v in enumerate(values))
    last = values[-1]
    lx, ly = (len(values) - 1) * step, h - 6 - (last - lo) / span * (h - 12)
    return ('<svg class="spark" viewBox="-4 0 %d %d" width="100%%" height="%d" role="img" aria-label="trend">'
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round"/>'
            '<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/></svg>' % (w + 8, h, h, pts, color, lx, ly, color))


def bar(value, limit):
    pct = min(100.0, value / limit * 100) if limit else 0
    cls = "bad" if value > limit else ("warn" if pct > 75 else "ok")
    return '<div class="bar"><span class="%s" style="width:%.1f%%"></span></div>' % (cls, pct)


def render(report, snap, hist, th, lang):
    t = L.get(lang, L["en"])
    e = html.escape
    fmt = (lambda n: "{:,}".format(n).replace(",", ".")) if lang == "es" else (lambda n: "{:,}".format(n))
    cards = []
    for key, label, desc, limit in (("always", t["always"], t["always_d"], th["tokens_always_loaded_warn"]),
                                    ("shared", t["shared"], t["shared_d"], th["tokens_shared_memory_warn"]),
                                    ("corpus", t["corpus"], t["corpus_d"], th["tokens_corpus_index"])):
        extra = ('<p class="mut">%s ≈%s</p>' % (e(t["skills"]), fmt(snap["skills"]))) if key == "always" else ""
        cards.append('<div class="card"><h3>%s</h3><div class="big">≈%s</div>%s<p class="mut">%s · %s</p>%s</div>'
                     % (e(label), fmt(snap[key]), bar(snap[key], limit), e(desc),
                        e(t["limit"].format(x=fmt(limit))), extra))
    rows = []
    for group, label in (("always_loaded", t["always"]), ("shared_memory", t["shared"]), ("corpus", t["corpus"])):
        for prov, r in (report.get("groups", {}).get(group) or {}).items():
            rows.append("<tr><td>%s</td><td>%s</td><td class='num'>%s</td><td class='mut'>%s</td></tr>"
                        % (e(label), e(prov), fmt(int(r.get("tokens", 0))), e(str(r.get("source", "")))))
    files = "".join("<li><code>%s</code> <span class='mut'>≈%s</span></li>" % (e(f["path"]), fmt(int(f["tokens"])))
                    for f in report.get("files", [])[:8])
    recs = report.get("recommendations") or []
    recs_html = "".join("<li>%s</li>" % e(r) for r in recs) or "<li class='okt'>%s</li>" % e(t["none"])
    if len(hist) >= 2:
        trend = "".join('<div class="tr"><span>%s</span>%s</div>' % (e(lbl), sparkline([h.get(k, 0) for h in hist], c))
                        for k, lbl, c in (("always", t["always"], "#2D6A8E"), ("shared", t["shared"], "#2B7A57"),
                                          ("corpus", t["corpus"], "#B0744A")))
    else:
        trend = "<p class='mut'>%s</p>" % e(t["trend_n"])
    return TEMPLATE.format(lang=e(lang or "en"), title=e(t["title"]), sub=e(t["sub"]), cards="".join(cards),
                           providers=e(t["providers"]), family="", h_group=e(t["family"]), h_tokens=e(t["tokens"]),
                           h_source=e(t["source"]), rows="".join(rows), heavy=e(t["heavy"]), files=files,
                           recs_t=e(t["recs"]), recs=recs_html, trend_t=e(t["trend"]), trend=trend,
                           est=e(t["est"]), gen=e(t["gen"].format(d=date.today().isoformat())))


TEMPLATE = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title><style>
:root{{--bg:#F5F3EF;--panel:#FFFFFF;--ink:#1C1A17;--mut:#78716A;--line:#E5E0D8;--acc:#2D6A8E;--ok:#2B7A57;
--warn:#9C640F;--bad:#AF3838;--track:#EEEAE4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0A0D12;--panel:#141920;--ink:#EDEFF3;--mut:#8D95A2;--line:#262D36;
--acc:#8DC1E1;--ok:#72D5A5;--warn:#F1C46C;--bad:#F28D8D;--track:#1E252E;color-scheme:dark}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:28px 16px 48px}}
.wrap{{max-width:880px;margin:0 auto}}h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:15px;margin:26px 0 10px}}
h3{{font-size:13px;margin:0 0 6px;color:var(--mut);font-weight:600}}.mut{{color:var(--mut);font-size:12.5px;margin:6px 0 0}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:16px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;min-width:0}}
.big{{font-size:26px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.bar{{height:8px;background:var(--track);border-radius:99px;overflow:hidden;margin-top:8px}}
.bar span{{display:block;height:100%}}.bar .ok{{background:var(--ok)}}.bar .warn{{background:var(--warn)}}
.bar .bad{{background:var(--bad)}}.tbl{{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px}}
table{{width:100%;border-collapse:collapse;min-width:520px}}th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line)}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}}td.num{{text-align:right;
font-variant-numeric:tabular-nums}}ul{{margin:0;padding-left:20px}}li{{margin:4px 0}}code{{font:12.5px ui-monospace,Menlo,monospace}}
.okt{{color:var(--ok)}}.box{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px}}
.tr{{display:grid;grid-template-columns:150px 1fr;gap:10px;align-items:center}}.spark{{max-width:100%}}
footer{{margin-top:22px;color:var(--mut);font-size:12px}}
</style></head><body><div class="wrap"><h1>{title}</h1><p class="mut">{sub}</p>
<div class="cards">{cards}</div>
<h2>{recs_t}</h2><div class="box"><ul>{recs}</ul></div>
<h2>{trend_t}</h2><div class="box">{trend}</div>
<h2>{providers}</h2><div class="tbl"><table><thead><tr><th></th><th>{h_group}</th><th>{h_tokens}</th>
<th>{h_source}</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>{heavy}</h2><div class="box"><ul>{files}</ul></div>
<footer>{est}<br>{gen}</footer></div></body></html>
"""


def serve_file(path, port, seconds):
    """Internal: serve one file on 127.0.0.1 for a while (used to open it in Orca's browser)."""
    data = open(path, "rb").read()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    srv.timeout = 1
    end = time.time() + seconds
    while time.time() < end:
        srv.handle_request()


def open_report(root, path, f):
    if f["in_orca"]:
        port = launch_free_port()
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "_serve", path, str(port), "600"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(0.4)
        ok, why = launch.open_orca("http://127.0.0.1:%d/" % port)
        if ok:
            return "opened in Orca's browser"
        if why == "not_added":
            return launch.NOT_ADDED.format(root=root) + " Report: " + path
    if f["display"] and not f["remote"] and not f["in_orca"]:
        ok, _ = launch.open_local("file://" + path)
        if ok:
            return "opened in your browser"
    if launch.preview_skill_dir(root):
        return "to show it: python3 .agents/skills/remote-preview/preview.py serve %s" % os.path.dirname(path)
    if f["remote"]:
        return launch.NO_PRIVATE_CHANNEL.format(ssh="python3 -m http.server --bind 127.0.0.1 8790 --directory %s "
                                                    "+ %s" % (os.path.dirname(path), launch.ssh_forward(8790)))
    return path


def launch_free_port():
    import socket  # noqa: PLC0415
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main(argv=None, env=None, agate=launch.run_agate):
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["_serve"]:
        serve_file(argv[1], int(argv[2]), int(argv[3]))
        return 0
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--exact", action="store_true")
    a = ap.parse_args(argv)
    root = launch.find_root()
    rc, out, err = agate(root, ["tokens", "--json"] + (["--exact"] if a.exact else []), timeout=300)
    try:
        report = json.loads(out)
        if not isinstance(report, dict):
            raise ValueError
    except ValueError:
        print("context-meter: `agate.py tokens --json` failed: " + (err or out or "no output").strip()[:160])
        return 1
    snap = summarize(report, root)
    hist = append_history(root, snap)
    lang = launch.language(root)
    page = render(report, snap, hist, thresholds(root), lang)
    if a.save:
        d = date.today()
        path = os.path.join(root, "artifacts", d.strftime("%Y-%m"), d.isoformat() + "-context-meter.html")
    else:
        path = os.path.join(root, "memory", "local", ".cache", "context-meter.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    recs = report.get("recommendations") or []
    print("context: always ≈{:,} (skills ≈{:,}) · shared ≈{:,} · corpus ≈{:,} · {}".format(
        snap["always"], snap["skills"], snap["shared"], snap["corpus"], recs[0] if recs else "no action needed"))
    where = open_report(root, path, launch.facts(env)) if a.open else os.path.relpath(path, root)
    print("report: " + where + (" (add a line to artifacts/INDEX.md)" if a.save else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
