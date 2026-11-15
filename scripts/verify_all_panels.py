import json
import urllib.request
from pathlib import Path

GRAFANA_URL = "http://127.0.0.1:3000/api/ds/query"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Basic YWRtaW46YWRtaW4="
}

dash_file = Path("/home/minhchien/project/IoT Project/infrastructure/grafana/dashboards/smart_agriculture_dashboard.json")
with open(dash_file, "r", encoding="utf-8") as f:
    dashboard = json.load(f)

panels = [p for p in dashboard.get("panels", []) if p.get("type") not in ("row", None)]
print(f"Total panels to verify: {len(panels)}")

passed = 0
for p in panels:
    pid = p.get("id")
    title = p.get("title")
    ptype = p.get("type")
    targets = p.get("targets", [])
    if not targets:
        print(f"Panel {pid}: {title} has no targets. Skipping.")
        continue
    
    t = targets[0]
    ds_uid = t.get("datasource", {}).get("uid")
    ds_type = t.get("datasource", {}).get("type")
    
    query_obj = {
        "refId": "A",
        "datasource": {"uid": ds_uid, "type": ds_type}
    }
    
    if ds_type == "influxdb":
        flux = t.get("query", "").replace("v.timeRangeStart", "-15m").replace("v.timeRangeStop", "now()")
        query_obj["query"] = flux
    elif ds_type == "postgres":
        sql = t.get("rawSql", "")
        query_obj["rawSql"] = sql
        query_obj["format"] = t.get("format", "table")
        query_obj["editorMode"] = "code"

    payload = {
        "from": "now-15m",
        "to": "now",
        "queries": [query_obj]
    }

    req = urllib.request.Request(GRAFANA_URL, data=json.dumps(payload).encode("utf-8"), headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", {}).get("A", {})
            error = results.get("error")
            frames = results.get("frames", [])
            if error:
                print(f"[FAIL] Panel {pid} '{title}': ERROR: {error}")
            else:
                num_rows = sum(len(f.get("data", {}).get("values", [[]])[0]) for f in frames) if frames else 0
                print(f"[OK]   Panel {pid} ({ptype}) '{title}': {len(frames)} frames, {num_rows} data points/rows")
                passed += 1
    except Exception as exc:
        print(f"[FAIL] Panel {pid} '{title}': HTTP error: {exc}")

print(f"\nResult: {passed}/{len(panels)} panels verified OK!")
