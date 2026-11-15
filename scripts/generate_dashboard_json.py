import json
from pathlib import Path

dashboard = {
  "annotations": {
    "list": [
      {
        "builtIn": 1,
        "datasource": {
          "type": "grafana",
          "uid": "-- Grafana --"
        },
        "enable": True,
        "hide": True,
        "name": "Annotations & Alerts",
        "type": "dashboard"
      }
    ]
  },
  "editable": True,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 1,
  "id": None,
  "links": [],
  "liveNow": True,
  "panels": [
    {
      "collapsed": False,
      "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
      "id": 100,
      "title": "THÔNG SỐ MÔI TRƯỜNG HIỆN TẠI (REALTIME METRICS)",
      "type": "row"
    },
    {
      "id": 1,
      "title": "Temperature (Nhiệt độ hiện tại)",
      "type": "stat",
      "datasource": {
        "type": "influxdb",
        "uid": "influxdb-flux"
      },
      "gridPos": {"h": 5, "w": 8, "x": 0, "y": 1},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "thresholds"},
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": None},
              {"color": "#EAB839", "value": 30},
              {"color": "red", "value": 35}
            ]
          },
          "unit": "celsius"
        },
        "overrides": []
      },
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": {
          "calcs": ["lastNotNull"],
          "fields": "",
          "values": False
        },
        "textMode": "auto"
      },
      "pluginVersion": "11.3.0",
      "targets": [
        {
          "datasource": {
            "type": "influxdb",
            "uid": "influxdb-flux"
          },
          "query": "from(bucket: \"smart_agriculture\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r[\"_measurement\"] == \"sensor_readings\")\n  |> filter(fn: (r) => r[\"sensor_id\"] == \"SEN-001\")\n  |> filter(fn: (r) => r[\"_field\"] == \"value\")\n  |> drop(columns: [\"event_id\", \"gateway_id\"])\n  |> group(columns: [\"sensor_id\", \"_field\"])\n  |> last()",
          "refId": "A"
        }
      ]
    },
    {
      "id": 2,
      "title": "Air Humidity (Độ ẩm không khí)",
      "type": "stat",
      "datasource": {
        "type": "influxdb",
        "uid": "influxdb-flux"
      },
      "gridPos": {"h": 5, "w": 8, "x": 8, "y": 1},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "thresholds"},
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": None},
              {"color": "green", "value": 40}
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": {
          "calcs": ["lastNotNull"],
          "fields": "",
          "values": False
        },
        "textMode": "auto"
      },
      "pluginVersion": "11.3.0",
      "targets": [
        {
          "datasource": {
            "type": "influxdb",
            "uid": "influxdb-flux"
          },
          "query": "from(bucket: \"smart_agriculture\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r[\"_measurement\"] == \"sensor_readings\")\n  |> filter(fn: (r) => r[\"sensor_id\"] == \"SEN-002\")\n  |> filter(fn: (r) => r[\"_field\"] == \"value\")\n  |> drop(columns: [\"event_id\", \"gateway_id\"])\n  |> group(columns: [\"sensor_id\", \"_field\"])\n  |> last()",
          "refId": "A"
        }
      ]
    },
    {
      "id": 3,
      "title": "Soil Moisture (Độ ẩm đất)",
      "type": "stat",
      "datasource": {
        "type": "influxdb",
        "uid": "influxdb-flux"
      },
      "gridPos": {"h": 5, "w": 8, "x": 16, "y": 1},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "thresholds"},
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": None},
              {"color": "green", "value": 30},
              {"color": "blue", "value": 35}
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": {
          "calcs": ["lastNotNull"],
          "fields": "",
          "values": False
        },
        "textMode": "auto"
      },
      "pluginVersion": "11.3.0",
      "targets": [
        {
          "datasource": {
            "type": "influxdb",
            "uid": "influxdb-flux"
          },
          "query": "from(bucket: \"smart_agriculture\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r[\"_measurement\"] == \"sensor_readings\")\n  |> filter(fn: (r) => r[\"sensor_id\"] == \"SEN-003\")\n  |> filter(fn: (r) => r[\"_field\"] == \"value\")\n  |> drop(columns: [\"event_id\", \"gateway_id\"])\n  |> group(columns: [\"sensor_id\", \"_field\"])\n  |> last()",
          "refId": "A"
        }
      ]
    },
    {
      "collapsed": False,
      "gridPos": {"h": 1, "w": 24, "x": 0, "y": 6},
      "id": 101,
      "title": "BIẾN ĐỘNG DỮ LIỆU THEO THỜI GIAN (TRENDS & HISTORY)",
      "type": "row"
    },
    {
      "id": 4,
      "title": "Temperature Trend (Biến động nhiệt độ)",
      "type": "timeseries",
      "datasource": {
        "type": "influxdb",
        "uid": "influxdb-flux"
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 7},
      "fieldConfig": {
        "defaults": {
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "smooth",
            "lineWidth": 2,
            "pointSize": 5,
            "showPoints": "auto",
            "spanNulls": True,
            "thresholdsStyle": {
              "mode": "line"
            }
          },
          "color": {"mode": "palette-classic"},
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": None},
              {"color": "red", "value": 35}
            ]
          },
          "unit": "celsius"
        },
        "overrides": []
      },
      "options": {
        "legend": {"calcs": ["min", "max", "last"], "displayMode": "table", "placement": "bottom"},
        "tooltip": {"mode": "single", "sort": "none"}
      },
      "targets": [
        {
          "datasource": {
            "type": "influxdb",
            "uid": "influxdb-flux"
          },
          "query": "from(bucket: \"smart_agriculture\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r[\"_measurement\"] == \"sensor_readings\")\n  |> filter(fn: (r) => r[\"sensor_id\"] == \"SEN-001\")\n  |> filter(fn: (r) => r[\"_field\"] == \"value\")\n  |> keep(columns: [\"_time\", \"_value\", \"sensor_id\"])\n  |> sort(columns: [\"_time\"])",
          "refId": "A"
        }
      ]
    },
    {
      "id": 5,
      "title": "Soil Moisture Trend (Biến động độ ẩm đất)",
      "type": "timeseries",
      "datasource": {
        "type": "influxdb",
        "uid": "influxdb-flux"
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 7},
      "fieldConfig": {
        "defaults": {
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "smooth",
            "lineWidth": 2,
            "pointSize": 5,
            "showPoints": "auto",
            "spanNulls": True,
            "thresholdsStyle": {
              "mode": "line"
            }
          },
          "color": {"mode": "palette-classic"},
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": None},
              {"color": "green", "value": 30},
              {"color": "blue", "value": 35}
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "options": {
        "legend": {"calcs": ["min", "max", "last"], "displayMode": "table", "placement": "bottom"},
        "tooltip": {"mode": "single", "sort": "none"}
      },
      "targets": [
        {
          "datasource": {
            "type": "influxdb",
            "uid": "influxdb-flux"
          },
          "query": "from(bucket: \"smart_agriculture\")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r[\"_measurement\"] == \"sensor_readings\")\n  |> filter(fn: (r) => r[\"sensor_id\"] == \"SEN-003\")\n  |> filter(fn: (r) => r[\"_field\"] == \"value\")\n  |> keep(columns: [\"_time\", \"_value\", \"sensor_id\"])\n  |> sort(columns: [\"_time\"])",
          "refId": "A"
        }
      ]
    },
    {
      "collapsed": False,
      "gridPos": {"h": 1, "w": 24, "x": 0, "y": 15},
      "id": 102,
      "title": "TRẠNG THÁI HỆ THỐNG & VẬN HÀNH (SYSTEM OPERATIONS)",
      "type": "row"
    },
    {
      "id": 6,
      "title": "Sensor Status (Trạng thái cảm biến)",
      "type": "table",
      "datasource": {
        "type": "postgres",
        "uid": "postgresql"
      },
      "gridPos": {"h": 7, "w": 10, "x": 0, "y": 16},
      "fieldConfig": {
        "defaults": {
          "custom": {
            "align": "auto",
            "cellOptions": {"type": "auto"},
            "inspect": False
          },
          "mappings": []
        },
        "overrides": [
          {
            "matcher": {"id": "byName", "options": "Trạng thái"},
            "properties": [
              {
                "id": "custom.cellOptions",
                "value": {"type": "color-background"}
              },
              {
                "id": "mappings",
                "value": [
                  {
                    "type": "value",
                    "options": {
                      "ONLINE": {"color": "green", "index": 0},
                      "STALE": {"color": "orange", "index": 1},
                      "OFFLINE": {"color": "red", "index": 2}
                    }
                  }
                ]
              }
            ]
          }
        ]
      },
      "options": {
        "cellHeight": "sm",
        "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False},
        "showHeader": True
      },
      "targets": [
        {
          "datasource": {
            "type": "postgres",
            "uid": "postgresql"
          },
          "editorMode": "code",
          "format": "table",
          "rawQuery": True,
          "rawSql": """WITH registry AS (
  SELECT 'SEN-001' AS sensor_id, 'Temperature' AS sensor_name, '°C' AS unit
  UNION ALL SELECT 'SEN-002', 'Air Humidity', '%'
  UNION ALL SELECT 'SEN-003', 'Soil Moisture', '%'
),
latest AS (
  SELECT DISTINCT ON (sensor_id)
    sensor_id,
    measurement_time,
    received_at,
    value
  FROM ingested_events
  WHERE processing_status = 'STORED'
  ORDER BY sensor_id, measurement_time DESC
)
SELECT
  r.sensor_id AS "Mã cảm biến",
  r.sensor_name AS "Tên cảm biến",
  COALESCE(ROUND(l.value::numeric, 1)::text || ' ' || r.unit, 'Chưa có') AS "Giá trị mới nhất",
  COALESCE(to_char(l.measurement_time AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'), 'Chưa có') AS "Thời điểm đo (UTC)",
  CASE
    WHEN l.received_at IS NULL THEN 'OFFLINE'
    WHEN NOW() - l.received_at < INTERVAL '30 seconds' THEN 'ONLINE'
    WHEN NOW() - l.received_at < INTERVAL '60 seconds' THEN 'STALE'
    ELSE 'OFFLINE'
  END AS "Trạng thái"
FROM registry r
LEFT JOIN latest l ON r.sensor_id = l.sensor_id
ORDER BY r.sensor_id;""",
          "refId": "A"
        }
      ]
    },
    {
      "id": 7,
      "title": "Pump Status (Trạng thái máy bơm ảo)",
      "type": "stat",
      "datasource": {
        "type": "postgres",
        "uid": "postgresql"
      },
      "gridPos": {"h": 7, "w": 6, "x": 10, "y": 16},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "thresholds"},
          "mappings": [
            {
              "type": "value",
              "options": {
                "ON (ĐANG TƯỚI)": {"color": "green", "index": 0},
                "OFF (NGỪNG TƯỚI)": {"color": "semi-dark-blue", "index": 1},
                "HOLD (DUY TRÌ)": {"color": "orange", "index": 2}
              }
            }
          ],
          "thresholds": {
            "mode": "absolute",
            "steps": [{"color": "text", "value": None}]
          }
        },
        "overrides": []
      },
      "options": {
        "colorMode": "background",
        "graphMode": "none",
        "justifyMode": "center",
        "orientation": "auto",
        "reduceOptions": {
          "calcs": ["lastNotNull"],
          "fields": "/Trạng thái bơm/",
          "values": False
        },
        "textMode": "auto"
      },
      "targets": [
        {
          "datasource": {
            "type": "postgres",
            "uid": "postgresql"
          },
          "editorMode": "code",
          "format": "table",
          "rawQuery": True,
          "rawSql": """WITH latest_soil AS (
  SELECT value, measurement_time
  FROM ingested_events
  WHERE sensor_id = 'SEN-003' AND processing_status = 'STORED'
  ORDER BY measurement_time DESC
  LIMIT 1
)
SELECT
  CASE
    WHEN value IS NULL THEN 'OFF (NGỪNG TƯỚI)'
    WHEN value < 30.0 THEN 'ON (ĐANG TƯỚI)'
    WHEN value > 35.0 THEN 'OFF (NGỪNG TƯỚI)'
    ELSE 'HOLD (DUY TRÌ)'
  END AS "Trạng thái bơm"
FROM (
  SELECT (SELECT value FROM latest_soil) AS value
) t;""",
          "refId": "A"
        }
      ]
    },
    {
      "id": 8,
      "title": "Sync Status (Dữ liệu đã đồng bộ & Chờ xử lý)",
      "type": "stat",
      "datasource": {
        "type": "postgres",
        "uid": "postgresql"
      },
      "gridPos": {"h": 7, "w": 8, "x": 16, "y": 16},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "thresholds"},
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": None}
            ]
          }
        },
        "overrides": [
          {
            "matcher": {"id": "byName", "options": "Chờ Influx (PENDING)"},
            "properties": [
              {
                "id": "thresholds",
                "value": {
                  "mode": "absolute",
                  "steps": [
                    {"color": "green", "value": None},
                    {"color": "yellow", "value": 1},
                    {"color": "red", "value": 10}
                  ]
                }
              }
            ]
          },
          {
            "matcher": {"id": "byName", "options": "Bị từ chối (REJECTED)"},
            "properties": [
              {
                "id": "thresholds",
                "value": {
                  "mode": "absolute",
                  "steps": [
                    {"color": "green", "value": None},
                    {"color": "red", "value": 1}
                  ]
                }
              }
            ]
          }
        ]
      },
      "options": {
        "colorMode": "value",
        "graphMode": "none",
        "justifyMode": "auto",
        "orientation": "horizontal",
        "reduceOptions": {
          "calcs": ["lastNotNull"],
          "fields": "",
          "values": False
        },
        "textMode": "auto"
      },
      "targets": [
        {
          "datasource": {
            "type": "postgres",
            "uid": "postgresql"
          },
          "editorMode": "code",
          "format": "table",
          "rawQuery": True,
          "rawSql": """SELECT
  (SELECT COUNT(*) FROM ingested_events WHERE processing_status = 'STORED') AS "Đã đồng bộ (STORED)",
  (SELECT COUNT(*) FROM ingested_events WHERE processing_status = 'PENDING_INFLUX') AS "Chờ Influx (PENDING)",
  (SELECT COUNT(*) FROM ingestion_rejections) AS "Bị từ chối (REJECTED)";""",
          "refId": "A"
        }
      ]
    },
    {
      "collapsed": False,
      "gridPos": {"h": 1, "w": 24, "x": 0, "y": 23},
      "id": 103,
      "title": "LỊCH SỬ CẢNH BÁO MÔI TRƯỜNG (ALERT HISTORY)",
      "type": "row"
    },
    {
      "id": 9,
      "title": "Alert History (Lịch sử cảnh báo vượt ngưỡng)",
      "type": "table",
      "datasource": {
        "type": "postgres",
        "uid": "postgresql"
      },
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 24},
      "fieldConfig": {
        "defaults": {
          "custom": {
            "align": "auto",
            "cellOptions": {"type": "auto"},
            "inspect": False
          },
          "mappings": []
        },
        "overrides": [
          {
            "matcher": {"id": "byName", "options": "Mức độ"},
            "properties": [
              {
                "id": "custom.cellOptions",
                "value": {"type": "color-background"}
              },
              {
                "id": "mappings",
                "value": [
                  {
                    "type": "value",
                    "options": {
                      "HIGH": {"color": "red", "index": 0},
                      "WARNING": {"color": "orange", "index": 1}
                    }
                  }
                ]
              }
            ]
          }
        ]
      },
      "options": {
        "cellHeight": "sm",
        "footer": {"countRows": True, "fields": "", "reducer": ["sum"], "show": True},
        "showHeader": True
      },
      "targets": [
        {
          "datasource": {
            "type": "postgres",
            "uid": "postgresql"
          },
          "editorMode": "code",
          "format": "table",
          "rawQuery": True,
          "rawSql": """SELECT
  event_id AS "Event ID",
  to_char(measurement_time AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS "Thời gian (UTC)",
  sensor_id AS "Mã cảm biến",
  CASE
    WHEN sensor_id = 'SEN-001' THEN 'Nhiệt độ cao (> 35°C)'
    WHEN sensor_id = 'SEN-002' THEN 'Độ ẩm thấp (< 40%)'
    WHEN sensor_id = 'SEN-003' THEN 'Độ ẩm đất thấp (< 30%)'
    ELSE 'Cảnh báo'
  END AS "Loại cảnh báo",
  CASE
    WHEN sensor_id = 'SEN-001' THEN 'HIGH'
    ELSE 'WARNING'
  END AS "Mức độ",
  ROUND(value::numeric, 1)::text || ' ' || unit AS "Giá trị đo"
FROM ingested_events
WHERE processing_status = 'STORED'
  AND (
    (sensor_id = 'SEN-001' AND value > 35.0)
    OR (sensor_id = 'SEN-002' AND value < 40.0)
    OR (sensor_id = 'SEN-003' AND value < 30.0)
  )
ORDER BY measurement_time DESC
LIMIT 50;""",
          "refId": "A"
        }
      ]
    }
  ],
  "refresh": "5s",
  "schemaVersion": 39,
  "tags": ["agriculture", "iot", "monitoring"],
  "templating": {"list": []},
  "time": {
    "from": "now-30m",
    "to": "now"
  },
  "timepicker": {
    "refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]
  },
  "timezone": "browser",
  "title": "Smart Agriculture Monitoring Dashboard",
  "uid": "smart-agriculture-overview",
  "version": 3,
  "weekStart": ""
}

dest_path = Path("/home/minhchien/project/IoT Project/infrastructure/grafana/dashboards/smart_agriculture_dashboard.json")
with open(dest_path, "w", encoding="utf-8") as f:
    json.dump(dashboard, f, indent=2, ensure_ascii=False)

print(f"Generated optimized dashboard JSON successfully at: {dest_path}")
