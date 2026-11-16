"""Run each provisioned Grafana panel query using its local dashboard JSON."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "infrastructure" / "grafana" / "dashboards" / "smart_agriculture_dashboard.json"


def flux_time(value: str) -> str:
    """Translate Grafana relative-time input into a Flux range expression."""
    if value == "now":
        return "now()"
    if value.startswith("now-") and re.fullmatch(r"now-[0-9]+[smhdw]", value):
        return value[3:]
    if value.endswith("Z") and "T" in value:
        return f'time(v: "{value}")'
    raise ValueError("Flux query range must be now, now-<duration>, or an ISO-8601 UTC timestamp")


def main() -> int:
    # Windows terminals may default to a legacy code page that cannot print
    # the Vietnamese panel titles. Keep verification output portable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("GRAFANA_URL", "http://127.0.0.1:3000"))
    parser.add_argument("--from", dest="time_from", default="now-15m")
    parser.add_argument("--to", dest="time_to", default="now")
    parser.add_argument("--require-data", action="store_true", help="Fail if any panel query returns zero rows")
    args = parser.parse_args()
    try:
        flux_start, flux_stop = flux_time(args.time_from), flux_time(args.time_to)
    except ValueError as exc:
        parser.error(str(exc))

    user = os.getenv("GRAFANA_USER", "admin")
    password = os.getenv("GRAFANA_PASSWORD", "admin")
    credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {credentials}"}
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    panels = [p for p in dashboard.get("panels", []) if p.get("type") not in ("row", None)]
    passed = 0
    failures = []
    print(f"Dashboard: {DASHBOARD.name}; panels: {len(panels)}; range: {args.time_from} .. {args.time_to}")

    for panel in panels:
        panel_id, title = panel.get("id"), panel.get("title", "(untitled)")
        targets = panel.get("targets", [])
        if not targets:
            failures.append(f"Panel {panel_id} '{title}' has no query target")
            continue

        target = targets[0]
        datasource = target.get("datasource") or panel.get("datasource") or {}
        query = {"refId": target.get("refId", "A"), "datasource": datasource}
        ds_type = datasource.get("type")
        if ds_type == "influxdb":
            flux = target.get("query", "")
            query["query"] = flux.replace("v.timeRangeStart", flux_start).replace(
                "v.timeRangeStop", flux_stop
            )
        elif ds_type == "postgres":
            query.update({
                "rawSql": target.get("rawSql", ""),
                "format": target.get("format", "table"),
                "editorMode": "code",
            })
        else:
            failures.append(f"Panel {panel_id} '{title}' uses unsupported datasource type {ds_type!r}")
            continue

        payload = json.dumps({
            "from": args.time_from,
            "to": args.time_to,
            "queries": [query],
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{args.url.rstrip('/')}/api/ds/query",
            data=payload,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
            result = body.get("results", {}).get(query["refId"], {})
            error = result.get("error")
            frames = result.get("frames", [])
            row_count = sum(
                max((len(values) for values in frame.get("data", {}).get("values", [])), default=0)
                for frame in frames
            )
            if error:
                failures.append(f"Panel {panel_id} '{title}': {error}")
            elif args.require_data and row_count == 0:
                failures.append(f"Panel {panel_id} '{title}' returned no rows")
            else:
                passed += 1
                print(f"[PASS] {panel_id} {title}: {len(frames)} frame(s), {row_count} row(s)")
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            failures.append(f"Panel {panel_id} '{title}': {exc}")

    for failure in failures:
        print(f"[FAIL] {failure}")
    print(f"\nResult: {passed}/{len(panels)} panels verified")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
