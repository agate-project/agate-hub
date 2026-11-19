#!/usr/bin/env python3
"""env-manager: let the person paste API keys into this project's .env without them passing through the AI.

  run.py --for <package>      form with every variable that package needs (most common)
  run.py --var NAME [--var …] form with just those variables
  run.py                      manage all variables (replace, add, verify, remove, new)
  run.py --plan               show where it would open, change nothing

The channel is chosen in code: Orca's browser → local browser → Tailscale with allowlist → SSH port-forward.
Public tunnels, claude.ai and the chat are never offered. Prints at most 3 lines; values are never printed.
"""

import argparse
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import launch  # noqa: E402
import server  # noqa: E402


def names_for(root, package, agate=launch.run_agate):
    rc, out, _ = agate(root, ["env", "check", "--json"])
    names = []
    try:
        for r in json.loads(out).get("vars", []):
            if package in (r.get("used_by") or []):
                names.append(r["name"])
    except ValueError:
        pass
    try:
        with open(os.path.join(root, ".agate", "env.json"), encoding="utf-8") as f:
            owners = json.load(f)
        for name, info in owners.items():
            fors = info.get("for") if isinstance(info, dict) else None
            fors = fors if isinstance(fors, list) else [fors]
            if package in fors and name not in names:
                names.append(name)
    except (OSError, ValueError, AttributeError):
        pass
    return names


def decide(root, f, forced=None):
    """(modes to try, notes). Pure apart from reading the project; `forced` may only narrow, never widen."""
    allow = launch.identities(root)
    modes, skipped = launch.plan(f, launch.preview_skill_dir(root), allow)
    if forced:
        if forced not in modes:
            return [], ["%s is not available here" % forced] + skipped
        modes = [forced]
    return modes, skipped


def main(argv=None, env=None):
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__.split("\n\n")[0],
                                 epilog="Values only go to `agate.py env set NAME --stdin`.")
    ap.add_argument("--var", action="append", default=[], metavar="NAME")
    ap.add_argument("--for", dest="package", metavar="PACKAGE")
    ap.add_argument("--mode", choices=("orca", "local", "tailscale"), help="force one allowed channel")
    ap.add_argument("--plan", action="store_true", help="show the decision and exit")
    ap.add_argument("--timeout", type=int, default=600, help="seconds (default 600)")
    a = ap.parse_args(argv)

    root = launch.find_root()
    f = launch.facts(env)
    modes, skipped = decide(root, f, a.mode)
    focus = [v.upper() for v in a.var]
    if a.package:
        focus += [n for n in names_for(root, a.package) if n not in focus]
        if not focus:
            print("env-manager: nothing registered for '%s' (use `agate.py env add NAME --for %s`)." % (
                a.package, a.package))
            return 2
    alt = "alt: python3 .agate/agate.py env set %s (terminal, hidden input)" % (focus[0] if focus else "NAME")
    if a.plan:
        print("%s · channels: %s%s" % (launch.where_line(f), ", ".join(modes) or "none",
                                       (" · skipped: " + "; ".join(skipped)) if skipped else ""))
        print(alt)
        return 0

    events = []
    st = server.State(root, focus=focus, lang=launch.language(root), idle_timeout=a.timeout,
                      on_event=events.append, package=a.package or "")
    srv = server.make_server(st)
    port = srv.server_address[1]
    st.hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
    local_url = "http://127.0.0.1:%d/?t=%s" % (port, st.token)
    serving = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.3}, daemon=True)
    serving.start()

    opened, handle = None, None
    for mode in modes:
        if mode == "orca":
            ok, _ = launch.open_orca(local_url)
            if ok:
                opened = "opened in Orca's browser"
                break
        elif mode == "local":
            ok, _ = launch.open_local(local_url)
            opened = "opened in your browser" if ok else "open on this computer: " + local_url
            break
        elif mode == "tailscale":
            url, handle, why = launch.expose_tailscale(root, port)
            if url:
                host = url.split("//", 1)[1].split("/", 1)[0].lower()
                st.hosts |= {host, host.split(":")[0]}
                st.mode, st.identity_header, st.allow = "tailscale", "Tailscale-User-Login", tuple(
                    launch.identities(root))
                opened = "give the person this private link (tailnet, only %s): %s?t=%s" % (
                    ", ".join(server._mask(x) for x in st.allow), url.rstrip("/") + "/", st.token)
                break
            skipped.append("tailscale: " + why)

    if not opened:
        if f["remote"]:
            print(launch.NO_PRIVATE_CHANNEL.format(ssh=launch.ssh_forward(port)))
            opened_line = "then open %s · %s" % (local_url, alt)
        else:
            srv.shutdown()
            srv.server_close()
            print("env-manager: could not open a browser here · " + alt)
            return 1
        print(opened_line)
    else:
        print("env-manager: %s (link works once; closes after saving or in %d min) · %s" % (
            opened, a.timeout // 60, launch.where_line(f)))
        print(alt)
    sys.stdout.flush()

    server.watchdog(st)
    try:
        while serving.is_alive():
            serving.join(0.5)
    except KeyboardInterrupt:
        srv.shutdown()
    finally:
        st.server = None
        srv.server_close()
        launch.unexpose(handle)
    print("; ".join(events) if events else "env-manager: closed without saving anything")
    return 0


if __name__ == "__main__":
    sys.exit(main())
