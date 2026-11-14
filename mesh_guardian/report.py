# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Anonymized diagnostic report (Markdown), to paste in an issue or a forum post.

No names, areas, addresses, prefixes or identifiers: nodes are numbered, border
routers are counted, only models, roles and figures are kept.
"""

import time


def _v(x, unit=""):
    return "—" if x is None else f"{x}{unit}"


def build(data, version):
    rows = data.get("rows") or []
    net = data.get("network") or {}
    q = data.get("quality") or {}
    brs = data.get("border_routers") or []
    alias = {r["name"]: f"N{i + 1}" for i, r in enumerate(sorted(rows, key=lambda r: (r.get("model") or "", r["name"])))}
    out = [f"## Mesh Guardian {version} — diagnostic report",
           "",
           f"Generated {time.strftime('%Y-%m-%d %H:%M')} — anonymized (no names, areas or addresses).",
           "",
           "### Network",
           "",
           f"- Matter nodes: {net.get('nodes')} ({net.get('unavailable')} unavailable), Thread nodes in the table: {len(rows)}",
           f"- Border routers: {sum(1 for b in brs if b.get('online'))}/{len(brs)} online, "
           f"roles: {', '.join(sorted(str(b.get('role')) for b in brs)) or '—'}",
           f"- Partitions: {net.get('partitions')}, storm: {'yes' if net.get('storm') else 'no'}, "
           f"routing problem: {'yes' if net.get('routing_problem') else 'no'}, automatic recovery: "
           f"{'on' if net.get('auto_recovery') else 'off'}"]
    if q.get("score") is not None:
        parts = ", ".join(f"{k} {v}" for k, v in (q.get("parts") or {}).items())
        out.append(f"- Quality: {q['score']} % (1h), {_v(q.get('score_24h'), ' %')} (24h) — {parts}; "
                   f"median response {_v(q.get('median_response_ms'), ' ms')}")
    roles = {}
    for r in rows:
        roles[r.get("role")] = roles.get(r.get("role"), 0) + 1
    out.append(f"- Roles: {', '.join(f'{k} {v}' for k, v in sorted(roles.items(), key=lambda x: str(x[0])))}")
    out += ["", "### Nodes", "",
            "| # | Model | Power | Role | Parent | RSSI | LQI | Neighbors | Outages 24h / 7d | Reboots 24h | Response avg | Advice |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: alias[r["name"]]):
        parent = r.get("parent")
        parent = alias.get(parent, "border router" if parent else "—")
        rssi = r.get("rssi") if r.get("rssi") is not None else r.get("best_rssi")
        lqi = r.get("lqi") if r.get("lqi") is not None else r.get("best_lqi")
        out.append(f"| {alias[r['name']]} | {r.get('model') or '?'} | {'battery' if r.get('battery') else 'mains'} | "
                   f"{r.get('role') or '?'} | {parent} | {_v(rssi)} | {_v(lqi)} | {_v(r.get('neighbors'))} | "
                   f"{_v(r.get('outages_24h'))} / {_v(r.get('outages_7d'))} | {_v(r.get('reboots_24h'))} | "
                   f"{_v(r.get('rtt_avg_ms'), ' ms')} | {'yes' if r.get('advice') else ''} |")
    return "\n".join(out) + "\n"
