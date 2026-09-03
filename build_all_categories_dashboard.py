"""
build_all_categories_dashboard.py
──────────────────────────────────────────────────────────────────────────────
Genera acc_all_categories_dashboard.html: réplica del dashboard de
ACC Motorcycles (acc_motorcycles_dashboard.html) pero con un selector de
categoría arriba que cubre las 10 categorías AGG1 de accesorios/repuestos de
vehículos, cada una con su propia apertura por AGG2 y por dominio.

Fuente: meli-sbox.PLANNINGMLA.BT_LIVE_LISTINGS_MLA

Uso:
    python build_all_categories_dashboard.py

Requiere:
    pip install google-cloud-bigquery pandas pyarrow
    gcloud auth application-default login
──────────────────────────────────────────────────────────────────────────────
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from google.cloud import bigquery
    import pandas as pd
except ImportError:
    print("ERROR: pip install google-cloud-bigquery pandas pyarrow")
    sys.exit(1)

HTML_PATH = Path(__file__).parent / "acc_all_categories_dashboard.html"
BQ_PROJECT = "meli-bi-data"
LISTINGS_TABLE = "`meli-sbox.PLANNINGMLA.BT_LIVE_LISTINGS_MLA`"

AGG1_LIST = [
    "ACC CARS & VANS",
    "ACC MOTORCYCLES",
    "ACC TOOLS",
    "ACC COMMERCIAL VEHICLES",
    "ACC VEHICULAR MULTIMEDIA",
    "OILS & FILTERS",
    "ACC NAUTICAL VEHICLES",
    "ACC TIRES",
    "ACC AGRO VEHICLES & EQUIPMENT",
    "VEHICLE BATTERIES",
]

RANGES = [
    ('01. Hasta 5K',    0,       5000),
    ('02. 5K a 15K',   5000,    15000),
    ('03. 15K a 33K',  15000,   33000),
    ('04. 33K a 50K',  33000,   50000),
    ('05. 50K a 75K',  50000,   75000),
    ('06. 75K a 90K',  75000,   90000),
    ('07. 90K a 120K', 90000,   120000),
    ('08. 120K a 150K',120000,  150000),
    ('09. 150K a 175K',150000,  175000),
    ('10. 175K a 220K',175000,  220000),
    ('11. 220K a 250K',220000,  250000),
    ('12. 250K a 300K',250000,  300000),
    ('13. 300K a 450K',300000,  450000),
    ('14. 450K a 600K',450000,  600000),
    ('15. 600K a 1M',  600000,  1000000),
    ('16. Mas de 1M',  1000000, None),
]
RANGE_KEYS = [r[0] for r in RANGES]

DOMAIN_PALETTE = [
    '#f0883e', '#58a6ff', '#a371f7', '#79c0ff', '#56d364', '#d2a8ff', '#ffa657',
    '#ff7b72', '#7ee787', '#39d353', '#bc8cff', '#ffa8a8', '#6ca4f0', '#e6b00a',
    '#8b949e', '#88a4c9', '#d29922', '#76e3ea', '#c9e4fa', '#f2a86f', '#b392f0',
    '#85e89d', '#f97583', '#ffab70', '#9ecbff', '#e1b96e', '#a5d6ff', '#ffd580',
    '#8ddb8c', '#ff9bce',
]
AGG2_PALETTE = ['#58a6ff', '#a371f7', '#f0883e', '#3fb950', '#e3b341', '#f85149', '#79c0ff']

MAX_DOMAINS_PER_CATEGORY = 30

# ─── PLAN SAN MARTÍN: rango 15K-33K, Free Shipping obligatorio ──────────────
SAN_MARTIN_RANGE_LABEL = RANGE_KEYS[2]  # '03. 15K a 33K'
SAN_MARTIN_RANGE_BOUNDS = (15000, 33000)
SAN_MARTIN_MONTHS_BACK = 6
SAN_MARTIN_MAX_DOMAINS_PER_AGG2 = 15


def slugify(name):
    n = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    n = re.sub(r'[^a-zA-Z0-9]+', '_', n).strip('_').lower()
    return n


def get_latest_photo_date(client):
    """Read latest partition id from INFORMATION_SCHEMA metadata (near-free, no full scan)."""
    sql = """
    SELECT partition_id
    FROM `meli-sbox.PLANNINGMLA.INFORMATION_SCHEMA.PARTITIONS`
    WHERE table_name = 'BT_LIVE_LISTINGS_MLA' AND partition_id != '__NULL__'
    ORDER BY partition_id DESC
    LIMIT 1
    """
    df = client.query(sql).to_dataframe()
    pid = str(df['partition_id'].iloc[0])
    return f"{pid[0:4]}-{pid[4:6]}-{pid[6:8]}"


def query_all_categories(client, photo_date, agg1_list):
    agg1_sql = "', '".join(a.replace("'", "\\'") for a in agg1_list)
    sql = f"""
    SELECT
      ITE_VERTICAL.DOM_DOMAIN_AGG1 AS agg1,
      ITE_VERTICAL.DOM_DOMAIN_AGG2 AS agg2,
      ITE_VERTICAL.DOM_DOMAIN_ID AS domain_id,
      ANY_VALUE(ITE_CAT.CAT_CATEG_NAME_L3) AS sample_l3,
      CASE
        WHEN BASE_PRICE < 5000     THEN '01. Hasta 5K'
        WHEN BASE_PRICE < 15000    THEN '02. 5K a 15K'
        WHEN BASE_PRICE < 33000    THEN '03. 15K a 33K'
        WHEN BASE_PRICE < 50000    THEN '04. 33K a 50K'
        WHEN BASE_PRICE < 75000    THEN '05. 50K a 75K'
        WHEN BASE_PRICE < 90000    THEN '06. 75K a 90K'
        WHEN BASE_PRICE < 120000   THEN '07. 90K a 120K'
        WHEN BASE_PRICE < 150000   THEN '08. 120K a 150K'
        WHEN BASE_PRICE < 175000   THEN '09. 150K a 175K'
        WHEN BASE_PRICE < 220000   THEN '10. 175K a 220K'
        WHEN BASE_PRICE < 250000   THEN '11. 220K a 250K'
        WHEN BASE_PRICE < 300000   THEN '12. 250K a 300K'
        WHEN BASE_PRICE < 450000   THEN '13. 300K a 450K'
        WHEN BASE_PRICE < 600000   THEN '14. 450K a 600K'
        WHEN BASE_PRICE < 1000000  THEN '15. 600K a 1M'
        ELSE                            '16. Mas de 1M'
      END AS range_label,
      CASE
        WHEN ITE_SHP.ITE_ITEM_SHIPPING_TAGS LIKE '%mandatory_free_shipping%' THEN 'con'
        ELSE 'sin'
      END AS fs_type,
      COUNT(*) AS listings,
      COUNTIF(ITE_PERFORMANCE.ORDERS_LAST_30DAYS > 0) AS successful,
      SUM(QUANTITY_AVAILABLE) AS stock
    FROM {LISTINGS_TABLE}
    WHERE PHOTO_DATE = '{photo_date}'
      AND ITE_VERTICAL.DOM_DOMAIN_AGG1 IN ('{agg1_sql}')
    GROUP BY 1, 2, 3, 5, 6
    """
    return client.query(sql).to_dataframe()


def make_cell(l, s, st):
    l, s, st = int(l), int(s), int(st)
    if l == 0:
        return None
    c = round(100.0 * s / l, 1)
    return {"l": l, "s": s, "c": c, "st": st}


def build_range_dict(sub_df):
    """sub_df grouped by range_label, fs_type -> {range_label: {con, sin}}"""
    agg = sub_df.groupby(['range_label', 'fs_type'])[['listings', 'successful', 'stock']].sum()
    out = {}
    for rk in RANGE_KEYS:
        cell = {'con': None, 'sin': None}
        for fs in ('con', 'sin'):
            if (rk, fs) in agg.index:
                row = agg.loc[(rk, fs)]
                cell[fs] = make_cell(row['listings'], row['successful'], row['stock'])
        out[rk] = cell
    return out


def build_categories(df):
    categories = {}
    cat_order = []

    cat_totals = df.groupby('agg1')['listings'].sum().sort_values(ascending=False)

    for agg1_raw in cat_totals.index:
        cat_key = slugify(agg1_raw)
        cat_order.append(cat_key)
        sub = df[df['agg1'] == agg1_raw]

        # AGG2 list ordered by total listings desc
        agg2_totals = sub.groupby('agg2')['listings'].sum().sort_values(ascending=False)
        agg2_list = []
        data = {'agg1': build_range_dict(sub)}
        for i, agg2_raw in enumerate(agg2_totals.index):
            a_key = slugify(agg2_raw)
            color = AGG2_PALETTE[i % len(AGG2_PALETTE)]
            label = agg2_raw.title()
            agg2_list.append({'key': a_key, 'label': label, 'raw': agg2_raw, 'color': color})
            data[a_key] = build_range_dict(sub[sub['agg2'] == agg2_raw])

        # Top domains by listings
        dom_totals = sub.groupby('domain_id')['listings'].sum().sort_values(ascending=False)
        top_domains = list(dom_totals.index[:MAX_DOMAINS_PER_CATEGORY])

        domain_labels = {}
        domain_colors = {}
        dd = {}
        for i, dom in enumerate(top_domains):
            dsub = sub[sub['domain_id'] == dom]
            l3_totals = dsub.groupby('sample_l3')['listings'].sum().sort_values(ascending=False)
            label = l3_totals.index[0] if len(l3_totals) else dom.replace('_', ' ').title()
            domain_labels[dom] = label
            domain_colors[dom] = DOMAIN_PALETTE[i % len(DOMAIN_PALETTE)]
            dd[dom] = build_range_dict(dsub)

        categories[cat_key] = {
            'key': cat_key,
            'label': agg1_raw,
            'agg2List': agg2_list,
            'DATA': data,
            'DOMAIN_ORDER': top_domains,
            'DOMAIN_LABELS': domain_labels,
            'DOMAIN_COLORS': domain_colors,
            'DD': dd,
            'totalDomains': int(dom_totals.shape[0]),
        }

    return categories, cat_order


def get_monthly_snapshot_dates(client, n_months=SAN_MARTIN_MONTHS_BACK):
    """Latest available partition day within each of the last n_months calendar
    months (metadata-only query, near-free), oldest first."""
    sql = """
    SELECT partition_id
    FROM `meli-sbox.PLANNINGMLA.INFORMATION_SCHEMA.PARTITIONS`
    WHERE table_name = 'BT_LIVE_LISTINGS_MLA' AND partition_id != '__NULL__'
    ORDER BY partition_id DESC
    """
    df = client.query(sql).to_dataframe()
    by_month = {}
    for pid in df['partition_id']:
        pid = str(pid)
        ym = pid[0:6]
        if ym not in by_month:
            by_month[ym] = pid  # first seen per month is the max (rows sorted desc)

    months_sorted = sorted(by_month.keys(), reverse=True)[:n_months]
    months_sorted.reverse()  # chronological order, oldest first
    out = []
    for ym in months_sorted:
        pid = by_month[ym]
        date_str = f"{pid[0:4]}-{pid[4:6]}-{pid[6:8]}"
        label = f"{pid[0:4]}-{pid[4:6]}"
        out.append((label, date_str))
    return out


def query_price_band_snapshot(client, date_str, agg1_list, lo, hi):
    agg1_sql = "', '".join(a.replace("'", "\\'") for a in agg1_list)
    hi_clause = f"AND BASE_PRICE < {hi}" if hi is not None else ""
    sql = f"""
    SELECT
      ITE_VERTICAL.DOM_DOMAIN_AGG1 AS agg1,
      ITE_VERTICAL.DOM_DOMAIN_AGG2 AS agg2,
      ITE_VERTICAL.DOM_DOMAIN_ID AS domain_id,
      ANY_VALUE(ITE_CAT.CAT_CATEG_NAME_L3) AS sample_l3,
      CASE
        WHEN ITE_SHP.ITE_ITEM_SHIPPING_TAGS LIKE '%mandatory_free_shipping%' THEN 'con'
        ELSE 'sin'
      END AS fs_type,
      COUNT(*) AS listings,
      COUNTIF(ITE_PERFORMANCE.ORDERS_LAST_30DAYS > 0) AS successful,
      SUM(QUANTITY_AVAILABLE) AS stock
    FROM {LISTINGS_TABLE}
    WHERE PHOTO_DATE = '{date_str}'
      AND ITE_VERTICAL.DOM_DOMAIN_AGG1 IN ('{agg1_sql}')
      AND BASE_PRICE >= {lo} {hi_clause}
    GROUP BY 1, 2, 3, 5
    """
    return client.query(sql).to_dataframe()


def build_san_martin(history_by_month, month_labels):
    """history_by_month: {month_label: df}. Returns nested AGG1 -> AGG2 -> domain
    tree with a monthly {con,sin} series at every level, all levels ordered by
    total SL (within this price band) descending."""
    frames = []
    for label, df in history_by_month.items():
        if df.empty:
            continue
        d = df.copy()
        d['month'] = label
        frames.append(d)
    if not frames:
        return {'months': month_labels, 'range': SAN_MARTIN_RANGE_LABEL, 'nodes': []}
    all_df = pd.concat(frames, ignore_index=True)

    def cell_for(sub):
        agg = sub.groupby('fs_type')[['listings', 'successful', 'stock']].sum()
        out = {'con': None, 'sin': None}
        for fs in ('con', 'sin'):
            if fs in agg.index:
                row = agg.loc[fs]
                out[fs] = make_cell(row['listings'], row['successful'], row['stock'])
        return out

    def monthly_series(sub):
        return {m: cell_for(sub[sub['month'] == m]) for m in month_labels}

    def total_sl(sub):
        return int(sub['successful'].sum())

    agg1_order = (all_df.groupby('agg1')['successful'].sum()
                  .sort_values(ascending=False).index)

    nodes = []
    for i, agg1_raw in enumerate(agg1_order):
        a1_sub = all_df[all_df['agg1'] == agg1_raw]
        agg2_order = (a1_sub.groupby('agg2')['successful'].sum()
                      .sort_values(ascending=False).index)

        agg2_children = []
        for j, agg2_raw in enumerate(agg2_order):
            a2_sub = a1_sub[a1_sub['agg2'] == agg2_raw]
            dom_order = (a2_sub.groupby('domain_id')['successful'].sum()
                         .sort_values(ascending=False).index)

            dom_children = []
            for k, dom in enumerate(dom_order[:SAN_MARTIN_MAX_DOMAINS_PER_AGG2]):
                d_sub = a2_sub[a2_sub['domain_id'] == dom]
                l3_totals = (d_sub.groupby('sample_l3')['listings'].sum()
                             .sort_values(ascending=False))
                label = l3_totals.index[0] if len(l3_totals) else dom.replace('_', ' ').title()
                dom_children.append({
                    'key': slugify(dom) or dom.lower(),
                    'label': label,
                    'color': DOMAIN_PALETTE[k % len(DOMAIN_PALETTE)],
                    'monthly': monthly_series(d_sub),
                })

            agg2_children.append({
                'key': slugify(agg2_raw),
                'label': agg2_raw.title(),
                'color': AGG2_PALETTE[j % len(AGG2_PALETTE)],
                'monthly': monthly_series(a2_sub),
                'children': dom_children,
            })

        nodes.append({
            'key': slugify(agg1_raw),
            'label': agg1_raw,
            'color': DOMAIN_PALETTE[i % len(DOMAIN_PALETTE)],
            'monthly': monthly_series(a1_sub),
            'children': agg2_children,
        })

    return {'months': month_labels, 'range': SAN_MARTIN_RANGE_LABEL, 'nodes': nodes}


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Accesorios & Repuestos de Vehículos — Live Listings Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
  background: #0d1117;
  color: #c9d1d9;
  font-size: 13px;
  min-height: 100vh;
  padding-bottom: 48px;
}

/* HEADER */
.header {
  background: #161b22;
  border-bottom: 1px solid #30363d;
  padding: 14px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-left { display: flex; align-items: center; gap: 14px; }
.header-right { display: flex; align-items: center; gap: 18px; }
.logo-badge {
  background: #ffe600;
  color: #0d1117;
  font-weight: 800;
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 4px;
  letter-spacing: 1px;
}
.header-title { font-size: 17px; font-weight: 600; color: #e6edf3; }
.header-meta { font-size: 11px; color: #8b949e; text-align: right; line-height: 1.8; }
.header-meta strong { color: #c9d1d9; }

/* SAN MARTÍN TOGGLE BUTTON (header action, not a tab pill) */
.sm-toggle-btn {
  display: flex; align-items: center; gap: 7px;
  padding: 9px 18px; border-radius: 8px;
  font-size: 12px; font-weight: 800; cursor: pointer;
  border: none; color: #0d1117; white-space: nowrap;
  background: linear-gradient(135deg, #58a6ff, #79c0ff);
  box-shadow: 0 2px 6px rgba(88,166,255,0.35);
  transition: transform 0.15s, box-shadow 0.15s, background 0.15s;
}
.sm-toggle-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(88,166,255,0.45); }
.sm-toggle-btn.active {
  background: #21262d; color: #f85149;
  border: 1px solid rgba(248,81,73,0.5); box-shadow: none;
}
.sm-toggle-btn.active:hover { background: #2d1618; transform: none; }

/* CATEGORY TABS */
.cat-tabs {
  display: flex; gap: 6px; flex-wrap: wrap;
  padding: 12px 28px;
  background: #0d1117;
  border-bottom: 1px solid #30363d;
}
.cat-tab {
  padding: 7px 16px; border-radius: 20px;
  font-size: 12px; font-weight: 700; cursor: pointer;
  border: 1px solid #30363d; color: #8b949e;
  background: #161b22; transition: all 0.15s;
}
.cat-tab.active { background: #ffe600; border-color: #ffe600; color: #0d1117; }
.cat-tab:hover:not(.active) { color: #e6edf3; border-color: #58a6ff; }

.hidden { display: none !important; }

/* TABS */
.nav-tabs {
  display: flex; gap: 4px;
  padding: 10px 28px;
  background: #161b22;
  border-bottom: 1px solid #30363d;
}
.nav-tab {
  padding: 6px 18px; border-radius: 6px;
  font-size: 13px; font-weight: 600; cursor: pointer;
  border: 1px solid transparent; color: #8b949e;
  background: none; transition: all 0.15s;
}
.nav-tab.active { background: #21262d; border-color: #30363d; color: #e6edf3; }
.nav-tab:hover:not(.active) { color: #c9d1d9; background: rgba(255,255,255,0.04); }
.tab-pane { display: none; }
.tab-pane.active { display: block; }

/* CONTENT */
.page { padding: 24px 28px; max-width: 1700px; margin: 0 auto; }

/* SECTION HEADER */
.section { margin-bottom: 36px; }
.section-head {
  display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
}
.s-bar { width: 4px; height: 22px; border-radius: 2px; flex-shrink: 0; }
.s-title { font-size: 15px; font-weight: 700; color: #e6edf3; }
.s-pill {
  font-size: 11px; color: #8b949e;
  background: #21262d; padding: 2px 10px;
  border-radius: 20px; border: 1px solid #30363d;
}

/* STAT TILES */
.stat-row {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 12px; margin-bottom: 18px;
}
.tile {
  background: #161b22; border: 1px solid #30363d;
  border-radius: 8px; padding: 14px 18px;
}
.tile-label {
  font-size: 10px; color: #8b949e;
  text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px;
}
.tile-value { font-size: 24px; font-weight: 700; color: #e6edf3; }
.tile-sub { font-size: 11px; color: #8b949e; margin-top: 3px; }

/* LEGEND */
.legend {
  display: flex; align-items: center; gap: 20px;
  margin-bottom: 10px; font-size: 11px; color: #8b949e;
}
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; }

/* ── INSIGHTS TAB ── */
.ins-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; margin-bottom: 28px; }
@media (max-width:1100px){ .ins-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width:700px) { .ins-grid { grid-template-columns: 1fr; } }
.ins-panel { background:#161b22; border:1px solid #30363d; border-radius:10px; overflow:hidden; }
.ins-panel-head { padding:12px 16px; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.5px; display:flex; align-items:center; gap:8px; }
.ins-panel-head.green  { background:rgba(63,185,80,.12);  color:#3fb950; border-bottom:1px solid rgba(63,185,80,.25); }
.ins-panel-head.yellow { background:rgba(210,167,36,.12); color:#e3b341; border-bottom:1px solid rgba(210,167,36,.25); }
.ins-panel-head.red    { background:rgba(248,81,73,.10);  color:#f85149; border-bottom:1px solid rgba(248,81,73,.25); }
.ins-item { padding:11px 16px; border-bottom:1px solid #21262d; display:flex; flex-direction:column; gap:3px; }
.ins-item:last-child { border-bottom:none; }
.ins-item-top { display:flex; align-items:center; gap:8px; }
.ins-rank { font-size:11px; font-weight:800; color:#484f58; min-width:18px; }
.ins-cat { font-size:12px; font-weight:700; color:#e6edf3; }
.ins-range { font-size:11px; color:#8b949e; }
.ins-metrics { display:flex; gap:10px; margin-top:1px; }
.ins-m { font-size:11px; }
.ins-m.hi   { color:#3fb950; font-weight:700; }
.ins-m.mid  { color:#e3b341; }
.ins-m.lo   { color:#f85149; }
.ins-m.muted{ color:#8b949e; }
.ins-why { font-size:10px; color:#6e7681; margin-top:2px; font-style:italic; line-height:1.4; }

/* domain insight rows */
.dom-ins-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:10px; }
.dom-ins-card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px 14px; }
.dom-ins-title { font-size:12px; font-weight:700; color:#e6edf3; margin-bottom:8px; display:flex; align-items:center; gap:7px; }
.dom-ins-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.dom-ins-row { display:flex; align-items:flex-start; gap:6px; font-size:11px; color:#c9d1d9; margin-bottom:5px; line-height:1.4; }
.dom-ins-row:last-child { margin-bottom:0; }
.dom-ins-badge { font-size:10px; font-weight:700; padding:1px 6px; border-radius:8px; flex-shrink:0; margin-top:1px; }
.dom-ins-badge.g { background:rgba(63,185,80,.15); color:#3fb950; }
.dom-ins-badge.y { background:rgba(227,179,65,.15); color:#e3b341; }
.dom-ins-badge.r { background:rgba(248,81,73,.12);  color:#f85149; }

/* TABLE */
.table-wrap { overflow-x: auto; border-radius: 8px; border: 1px solid #30363d; }
table { width: 100%; border-collapse: collapse; white-space: nowrap; }

thead tr:first-child th {
  background: #1c2128;
  padding: 9px 10px;
  font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.4px;
  border-bottom: 1px solid #30363d;
}
thead tr:last-child th {
  background: #161b22;
  padding: 6px 10px;
  font-size: 10px; font-weight: 600; color: #8b949e;
  border-bottom: 2px solid #30363d;
  text-align: right;
}
th.col-range { text-align: left !important; }
th.grp-con { color: #3fb950; border-left: 2px solid rgba(63,185,80,0.4); }
th.grp-sin { color: #768390; border-left: 2px solid #30363d; }

tbody tr:nth-child(even) { background: rgba(255,255,255,0.015); }
tbody tr:hover { background: rgba(255,255,255,0.04); }

td {
  padding: 6px 10px; border-bottom: 1px solid #21262d;
  text-align: right; color: #c9d1d9; font-variant-numeric: tabular-nums;
}
td.col-range {
  text-align: left; font-weight: 500;
  color: #e6edf3; font-size: 12px;
  width: 150px;
}
td.con-first { border-left: 2px solid rgba(63,185,80,0.4); }
td.sin-first { border-left: 2px solid #30363d; }
td.conv { font-weight: 700; font-size: 12px; }
td.empty { color: #30363d; }

tfoot td {
  padding: 8px 10px;
  border-top: 2px solid #30363d; border-bottom: none;
  font-weight: 700; color: #e6edf3;
  background: #1c2128;
}

/* AGG2 / DOMAIN CARDS */
.agg2-grid { display: flex; flex-direction: column; gap: 12px; }
.agg2-card { border: 1px solid #30363d; border-radius: 8px; overflow: hidden; }
.agg2-card-head {
  padding: 11px 14px; background: #161b22;
  display: flex; align-items: center; gap: 8px;
  cursor: pointer; user-select: none;
  transition: background 0.15s;
}
.agg2-card-head:hover { background: #1c2128; }
.agg2-card-title { font-size: 15px; font-weight: 700; color: #e6edf3; }
.agg2-card-sub { font-size: 10px; color: #8b949e; }
.agg2-card-count { font-size: 11px; color: #8b949e; margin-left: auto; }
.agg2-chevron {
  color: #484f58; font-size: 12px; margin-left: 10px;
  transition: transform 0.2s; flex-shrink: 0;
}
.agg2-card.open .agg2-chevron { transform: rotate(180deg); }
.agg2-card-body { display: none; border-top: 1px solid #30363d; }
.agg2-card.open .agg2-card-body { display: block; }
.agg2-card .table-wrap { border: none; border-radius: 0; }

/* FOOTER */
.footer {
  text-align: center; padding: 20px;
  font-size: 11px; color: #484f58;
  border-top: 1px solid #21262d; margin-top: 8px;
}

/* ── METODOLOGÍA BOX ── */
.metodologia {
  background: #161b22; border: 1px solid #30363d; border-radius: 8px;
  padding: 18px 22px; margin-bottom: 28px;
}
.metodologia-title { font-size: 12px; font-weight: 700; color: #e3b341; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; display: flex; align-items: center; gap: 7px; }
.metodologia-body { font-size: 12px; color: #8b949e; line-height: 1.7; }
.metodologia-body strong { color: #c9d1d9; }
.metodologia-steps { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.metodologia-step { display: flex; align-items: flex-start; gap: 10px; font-size: 12px; color: #8b949e; }
.metodologia-step-num { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; font-weight: 700; font-size: 11px; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }

/* ── PARETO / 80-20 TAB ── */
.pareto-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px; }
.pareto-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; }
.pareto-card-head { padding: 11px 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #21262d; }
.pareto-card-name { font-size: 13px; font-weight: 700; color: #e6edf3; flex: 1; }
.pareto-card-badge { font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 10px; }
.pareto-card-badge.concentrated { background: rgba(63,185,80,.15); color: #3fb950; }
.pareto-card-badge.dispersed    { background: rgba(248,81,73,.12);  color: #f85149; }
.pareto-card-badge.mid          { background: rgba(227,179,65,.12); color: #e3b341; }
.pareto-card-body { padding: 10px 14px; }
.pareto-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.pareto-row:last-child { margin-bottom: 0; }
.pareto-range { font-size: 11px; color: #8b949e; min-width: 120px; flex-shrink: 0; }
.pareto-bar-wrap { flex: 1; height: 14px; background: #21262d; border-radius: 3px; overflow: hidden; position: relative; }
.pareto-bar-fill { height: 100%; border-radius: 3px; }
.pareto-bar-fill.in80  { background: #3fb950; }
.pareto-bar-fill.out80 { background: #30363d; }
.pareto-sl-val { font-size: 11px; color: #c9d1d9; min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; }
.pareto-pct-val { font-size: 10px; color: #8b949e; min-width: 36px; text-align: right; }
.pareto-cutoff { border-top: 1px dashed rgba(227,179,65,0.5); margin: 4px 0 8px; display: flex; align-items: center; gap: 6px; padding-top: 6px; }
.pareto-cutoff-label { font-size: 10px; color: #e3b341; font-style: italic; }
.pareto-summary { font-size: 11px; color: #8b949e; padding: 8px 14px; border-top: 1px solid #21262d; background: rgba(255,255,255,.02); }
.pareto-summary strong { color: #e6edf3; }

/* ── BRECHA DE CONVERSIÓN TAB ── */
.brecha-bar-row {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 0; border-bottom: 1px solid #21262d;
}
.brecha-bar-row:last-child { border-bottom: none; }
.brecha-label { width: 220px; font-size: 12px; font-weight: 600; color: #e6edf3; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.brecha-bars { flex: 1; position: relative; height: 18px; background: #21262d; border-radius: 3px; overflow: hidden; }
.brecha-bar-sl { position: absolute; left: 0; top: 0; height: 100%; background: #3fb950; border-radius: 3px 0 0 3px; transition: width 0.4s; }
.brecha-bar-gap { position: absolute; top: 0; height: 100%; background: rgba(248,81,73,0.3); border-radius: 0 3px 3px 0; }
.brecha-pct-sl  { font-size: 11px; font-weight: 700; color: #3fb950; min-width: 36px; text-align: right; }
.brecha-pct-gap { font-size: 11px; color: #f85149; min-width: 36px; text-align: right; }
.brecha-nums { font-size: 11px; color: #8b949e; min-width: 120px; text-align: right; }

/* ── VISTA EJECUTIVA TAB ── */
.exec-hero { text-align: center; padding: 40px 28px 28px; }
.exec-hero-headline {
  font-size: 36px; font-weight: 800; color: #f85149; line-height: 1.2; margin-bottom: 12px;
}
.exec-hero-sub { font-size: 16px; color: #8b949e; }
.exec-kpi-row { display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin: 28px 0; }
.exec-kpi {
  background: #161b22; border: 1px solid #30363d; border-radius: 10px;
  padding: 20px 24px; text-align: center;
}
.exec-kpi-val { font-size: 32px; font-weight: 800; color: #e6edf3; }
.exec-kpi-label { font-size: 12px; color: #8b949e; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
.exec-kpi-note { font-size: 11px; color: #484f58; margin-top: 4px; }
.exec-top-title { font-size: 14px; font-weight: 700; color: #e6edf3; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
.exec-top-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.exec-rank { font-size: 20px; font-weight: 800; color: #484f58; min-width: 28px; }
.exec-dom-name { font-size: 13px; font-weight: 700; color: #e6edf3; min-width: 180px; }
.exec-gap-bar-wrap { flex: 1; height: 20px; background: #21262d; border-radius: 4px; overflow: hidden; position: relative; }
.exec-gap-bar { height: 100%; background: rgba(248,81,73,0.55); border-radius: 4px; }
.exec-gap-pct { font-size: 12px; font-weight: 700; color: #f85149; min-width: 50px; text-align: right; }
.exec-gap-abs { font-size: 11px; color: #8b949e; min-width: 80px; text-align: right; }
.exec-actions { background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 20px 24px; }
.exec-action-title { font-size: 13px; font-weight: 700; color: #e6edf3; margin-bottom: 14px; }
.exec-action-item { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px; padding-bottom: 14px; border-bottom: 1px solid #21262d; }
.exec-action-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.exec-action-num { background: #ffe600; color: #0d1117; font-size: 12px; font-weight: 800; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.exec-action-text { font-size: 13px; color: #c9d1d9; line-height: 1.5; }
.exec-action-text strong { color: #e6edf3; }

/* ── PLAN SAN MARTÍN ── */
.sm-tree { display: flex; flex-direction: column; gap: 10px; }
.sm-node-body-inner { padding: 12px 14px 14px 14px; }
.sm-children {
  margin-top: 12px; padding-left: 18px; padding-right: 6px;
  border-left: 2px solid #21262d; display: flex; flex-direction: column; gap: 10px;
  max-height: 420px; overflow-y: auto;
}
.sm-badge-pct { font-size: 12px; font-weight: 800; padding: 3px 10px; border-radius: 6px; }
.sm-delta { font-size: 11px; font-weight: 700; }
.sm-delta.up { color: #3fb950; }
.sm-delta.down { color: #f85149; }
.sm-child-count { font-size: 11px; color: #58a6ff; font-weight: 700; }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <span class="logo-badge">MELI</span>
    <span class="header-title" id="header-title">Live Listings Dashboard</span>
  </div>
  <div class="header-right">
    <button class="sm-toggle-btn" id="btn-sanmartin-global" onclick="toggleSanMartin(this)">🚚 Plan San Martín</button>
    <div class="header-meta">
      Datos al: <strong id="dashboard-photo-date">__PHOTO_DATE__</strong> &nbsp;·&nbsp; Fuente: BT_LIVE_LISTINGS_MLA<br>
      SL/LL = Successful Listings / Live Listings Live (últimos 30 días) &nbsp;·&nbsp; Actualización: Semanal
    </div>
  </div>
</div>

<div class="cat-tabs" id="cat-tabs"></div>

<div class="nav-tabs">
  <button class="nav-tab active" onclick="switchTab('agrupadores',this)">Agrupadores</button>
  <button class="nav-tab" onclick="switchTab('dominios',this)">Dominios</button>
  <button class="nav-tab" onclick="switchTab('insights',this)">Insights & Oportunidades</button>
  <button class="nav-tab" onclick="switchTab('brecha',this)">Brecha de Conversión</button>
  <button class="nav-tab" onclick="switchTab('ejecutiva',this)">Vista Ejecutiva</button>
  <button class="nav-tab" onclick="switchTab('pareto',this)">80/20</button>
  <button class="nav-tab" onclick="switchTab('aclaracion',this)">Aclaración</button>
</div>

<!-- ══════════════ PANE 1: AGRUPADORES ══════════════ -->
<div id="pane-agrupadores" class="tab-pane active">
<div class="page">

  <!-- AGG1 -->
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#ffe600"></div>
      <span class="s-title" id="agg1-title">—</span>
      <span class="s-pill">AGG1 — Vista consolidada</span>
    </div>
    <div class="stat-row" id="stats-agg1"></div>
    <div class="legend">
      <span>SL/LL — intensidad de color:</span>
      <span class="legend-item"><span class="legend-dot" style="background:rgba(63,185,80,0.15)"></span>Baja</span>
      <span class="legend-item"><span class="legend-dot" style="background:rgba(63,185,80,0.4)"></span>Media</span>
      <span class="legend-item"><span class="legend-dot" style="background:rgba(63,185,80,0.75)"></span>Alta</span>
    </div>
    <div class="table-wrap"><table id="table-agg1"></table></div>
  </div>

  <!-- AGG2 -->
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#58a6ff"></div>
      <span class="s-title">Apertura por AGG2</span>
      <span class="s-pill" id="agg2-section-pill">—</span>
    </div>
    <div class="agg2-grid" id="agg2-grid"></div>
  </div>

</div>
</div>

<!-- ══════════════ PANE 2: DOMINIOS ══════════════ -->
<div id="pane-dominios" class="tab-pane">
<div class="page">
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#ffe600"></div>
      <span class="s-title">Apertura por Dominio</span>
      <span class="s-pill" id="domains-pill">—</span>
    </div>
    <div class="legend" style="margin-bottom:20px">
      <span>SL/LL — intensidad de color:</span>
      <span class="legend-item"><span class="legend-dot" style="background:rgba(63,185,80,0.15)"></span>Baja</span>
      <span class="legend-item"><span class="legend-dot" style="background:rgba(63,185,80,0.4)"></span>Media</span>
      <span class="legend-item"><span class="legend-dot" style="background:rgba(63,185,80,0.75)"></span>Alta</span>
    </div>
    <div id="domains-container" class="agg2-grid"></div>
  </div>
</div>
</div>

<!-- ══════════════ PANE 3: INSIGHTS ══════════════ -->
<div id="pane-insights" class="tab-pane">
<div class="page">

  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#ffe600"></div>
      <span class="s-title">Insights & Oportunidades — Top Ranking Global</span>
      <span class="s-pill" id="ins-pill">Calculado automáticamente desde los datos de listings</span>
    </div>
    <div class="ins-grid">
      <div class="ins-panel">
        <div class="ins-panel-head green">🟢 Alta Demanda, Baja Oferta</div>
        <div id="ins-demand"></div>
      </div>
      <div class="ins-panel">
        <div class="ins-panel-head yellow">🟡 Activar Free Shipping</div>
        <div id="ins-fs"></div>
      </div>
      <div class="ins-panel">
        <div class="ins-panel-head red">🔴 Mercados Saturados — Evitar</div>
        <div id="ins-sat"></div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#58a6ff"></div>
      <span class="s-title">Diagnóstico por Dominio</span>
      <span class="s-pill">Mejor rango + alerta por categoría</span>
    </div>
    <div class="dom-ins-grid" id="ins-domains"></div>
  </div>

</div>
</div>

<!-- ══════════════ PANE 4: REGLA 80/20 ══════════════ -->
<div id="pane-pareto" class="tab-pane">
<div class="page">

  <!-- Metodología -->
  <div class="metodologia">
    <div class="metodologia-title">📐 Cómo se calcula este análisis</div>
    <div class="metodologia-body">
      Este análisis aplica el <strong>principio de Pareto (80/20)</strong> dentro de los <strong>Successful Listings (SL)</strong> de cada dominio:
      cuántos tramos de precio concentran el 80% de las conversiones totales del dominio.
    </div>
    <div class="metodologia-steps">
      <div class="metodologia-step">
        <div class="metodologia-step-num">1</div>
        <div>Por cada dominio, se calcula el <strong>SL por tramo de precio</strong> sumando los SL de Con FS y Sin FS (es decir, <code style="background:#21262d;padding:1px 5px;border-radius:3px;color:#c9d1d9">con.s + sin.s</code> para cada rango).</div>
      </div>
      <div class="metodologia-step">
        <div class="metodologia-step-num">2</div>
        <div>Los tramos se <strong>ordenan de mayor a menor SL</strong> para identificar cuáles son los más relevantes dentro de la categoría.</div>
      </div>
      <div class="metodologia-step">
        <div class="metodologia-step-num">3</div>
        <div>Se acumula el SL tramo a tramo y se marca el <strong>punto de corte al 80%</strong>: todos los rangos por encima de esa línea son los que dominan las ventas. Los que quedan debajo tienen impacto marginal.</div>
      </div>
      <div class="metodologia-step">
        <div class="metodologia-step-num">4</div>
        <div>Se clasifica el dominio según cuántos tramos hacen el 80%: <strong style="color:#3fb950">1–2 tramos = muy concentrado</strong> (foco claro), <strong style="color:#e3b341">3–4 = moderado</strong>, <strong style="color:#f85149">5+ = disperso</strong> (sin tramo dominante).</div>
      </div>
    </div>
  </div>

  <!-- Summary tiles -->
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#e3b341"></div>
      <span class="s-title">Concentración global de SL</span>
      <span class="s-pill" id="pareto-pill">Calculado automáticamente desde datos de listings</span>
    </div>
    <div class="stat-row" id="pareto-tiles"></div>
  </div>

  <!-- Cards por dominio -->
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#58a6ff"></div>
      <span class="s-title">Distribución por dominio</span>
      <span class="s-pill">Verde = tramos dentro del 80% · Gris = fuera del 80%</span>
    </div>
    <div class="pareto-grid" id="pareto-grid"></div>
  </div>

</div>
</div>

<!-- ══════════════ PANE 5: BRECHA DE CONVERSIÓN ══════════════ -->
<div id="pane-brecha" class="tab-pane">
<div class="page">

  <!-- Summary tiles -->
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#f85149"></div>
      <span class="s-title">Brecha de Conversión — Vista Global</span>
      <span class="s-pill" id="brecha-pill">Calculado automáticamente desde datos de listings</span>
    </div>
    <div class="stat-row" id="brecha-tiles"></div>
  </div>

  <!-- Horizontal bar chart by domain -->
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#58a6ff"></div>
      <span class="s-title">SL/LL por Dominio</span>
      <span class="s-pill">Verde = SL (convierte) · Rojo = Gap (no convierte)</span>
    </div>
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px;">
      <div style="display:flex;gap:20px;font-size:10px;color:#8b949e;margin-bottom:12px;">
        <span style="display:flex;align-items:center;gap:5px;"><span style="width:12px;height:12px;background:#3fb950;border-radius:2px;display:inline-block"></span>Exitosos (SL)</span>
        <span style="display:flex;align-items:center;gap:5px;"><span style="width:12px;height:12px;background:rgba(248,81,73,0.4);border-radius:2px;display:inline-block"></span>No convierten (Gap)</span>
      </div>
      <div id="brecha-bars"></div>
    </div>
  </div>

  <!-- Table -->
  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#e3b341"></div>
      <span class="s-title">Detalle por Dominio</span>
      <span class="s-pill">Ordenado por Gap absoluto (desc)</span>
    </div>
    <div class="table-wrap">
      <table id="brecha-table"></table>
    </div>
  </div>

</div>
</div>

<!-- ══════════════ PANE 6: VISTA EJECUTIVA ══════════════ -->
<div id="pane-ejecutiva" class="tab-pane">
<div class="page">

  <!-- Hero headline -->
  <div class="exec-hero" id="exec-hero"></div>

  <!-- 3 KPIs -->
  <div class="exec-kpi-row" id="exec-kpis"></div>

  <!-- Top 5 gap domains -->
  <div class="section">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
      <div>
        <div class="exec-top-title">
          <span style="color:#f85149">■</span>
          Top 5 categorías con mayor brecha
        </div>
        <div id="exec-top5"></div>
      </div>
      <div>
        <div class="exec-actions" id="exec-actions"></div>
      </div>
    </div>
  </div>

</div>
</div>

<!-- ══════════════ PANE: PLAN SAN MARTÍN ══════════════ -->
<div id="pane-sanmartin" class="tab-pane">
<div class="page">

  <div class="metodologia">
    <div class="metodologia-title">🚚 Plan San Martín — qué estamos monitoreando</div>
    <div class="metodologia-body">
      Con la implementación del <strong>Plan San Martín</strong>, el rango de precio <strong>15K a 33K (ASP)</strong>
      pasa a tener <strong>Free Shipping obligatorio</strong> en todas las categorías. Este panel sigue la migración
      Sin FS → Con FS mes a mes, y su impacto en SL/LL, en tres niveles: primero por categoría (AGG1), después por
      su apertura AGG2, y por último por dominio — todos ordenados por Successful Listings (SL) dentro de este rango.
      Click en cada fila para expandir el siguiente nivel.
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <div class="s-bar" style="background:#ffe600"></div>
      <span class="s-title">Evolución mensual — Rango 15K a 33K</span>
      <span class="s-pill" id="sm-pill">—</span>
    </div>
    <div class="sm-tree" id="sanmartin-tree"></div>
  </div>

</div>
</div>

<!-- ══════════════ PANE 7: ACLARACIÓN ══════════════ -->
<div id="pane-aclaracion" class="tab-pane">
<div class="page">

  <div style="max-width:860px;margin:0 auto;padding-top:8px;">

    <div style="margin-bottom:28px;">
      <div class="section-head">
        <div class="s-bar" style="background:#ffe600"></div>
        <span class="s-title">Glosario de métricas</span>
        <span class="s-pill">Fuente: BT_LIVE_LISTINGS_MLA</span>
      </div>

      <table style="width:100%;border-collapse:collapse;border:1px solid #30363d;border-radius:10px;overflow:hidden;">
        <thead>
          <tr style="background:#1c2128;">
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:#8b949e;border-bottom:2px solid #30363d;">Métrica</th>
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:#8b949e;border-bottom:2px solid #30363d;">Qué mide</th>
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:#8b949e;border-bottom:2px solid #30363d;">Período</th>
            <th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:#8b949e;border-bottom:2px solid #30363d;">Nota</th>
          </tr>
        </thead>
        <tbody>
          <tr style="background:#161b22;">
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;font-weight:700;color:#e6edf3;white-space:nowrap;">LL — Listings Live</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#c9d1d9;">Cantidad de listings activos en el marketplace</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#3fb950;font-weight:600;white-space:nowrap;">Foto puntual (PHOTO_DATE)</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#8b949e;font-size:12px;">Estado del catálogo en un día específico</td>
          </tr>
          <tr>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;font-weight:700;color:#e6edf3;white-space:nowrap;">SL — Successful Listings</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#c9d1d9;">Listings que recibieron <strong style="color:#e6edf3;">al menos 1 orden</strong> en los últimos 30 días</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#e3b341;font-weight:600;white-space:nowrap;">Ventana móvil 30 días</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#8b949e;font-size:12px;">Métrica binaria por listing: vendió o no vendió</td>
          </tr>
          <tr style="background:#161b22;">
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;font-weight:700;color:#e6edf3;white-space:nowrap;">SL/LL%</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#c9d1d9;">Porcentaje del catálogo activo que logró al menos una venta</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#e3b341;font-weight:600;white-space:nowrap;">Ventana móvil 30 días</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#8b949e;font-size:12px;">Proxy de conversión y salud del catálogo</td>
          </tr>
          <tr>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;font-weight:700;color:#e6edf3;white-space:nowrap;">Stock</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#c9d1d9;">Unidades disponibles declaradas en los listings activos</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#3fb950;font-weight:600;white-space:nowrap;">Foto puntual (PHOTO_DATE)</td>
            <td style="padding:11px 16px;border-bottom:1px solid #21262d;color:#8b949e;font-size:12px;">No es unidades vendidas, es disponibilidad declarada</td>
          </tr>
          <tr style="background:#161b22;">
            <td style="padding:11px 16px;font-weight:700;color:#8b949e;white-space:nowrap;">Facturación / NMV</td>
            <td style="padding:11px 16px;color:#8b949e;">No disponible en este dashboard</td>
            <td style="padding:11px 16px;color:#8b949e;">—</td>
            <td style="padding:11px 16px;color:#8b949e;font-size:12px;">Fuente separada: BT_ORD_ORDERS</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div style="margin-bottom:28px;">
      <div class="section-head">
        <div class="s-bar" style="background:#58a6ff"></div>
        <span class="s-title">Preguntas frecuentes</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px;">

        <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px;">
          <div style="font-size:13px;font-weight:700;color:#e3b341;margin-bottom:7px;">¿LL y SL son del mismo momento?</div>
          <div style="font-size:13px;color:#8b949e;line-height:1.7;">
            Técnicamente sí — ambos provienen de la misma foto (<strong style="color:#c9d1d9">PHOTO_DATE</strong>). La diferencia es que LL cuenta listings activos en ese día, mientras que SL usa el campo pre-calculado <code style="background:#0d1117;padding:1px 5px;border-radius:3px;color:#79c0ff;">ORDERS_LAST_30DAYS</code> que refleja actividad de los 30 días previos a esa foto.
          </div>
        </div>

        <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px;">
          <div style="font-size:13px;font-weight:700;color:#e3b341;margin-bottom:7px;">¿Un listing que vendió 100 unidades y uno que vendió 1 cuentan igual?</div>
          <div style="font-size:13px;color:#8b949e;line-height:1.7;">
            Sí. SL es binario: <strong style="color:#c9d1d9;">vendió o no vendió</strong>. El objetivo de SL/LL es medir la <em>salud del catálogo</em> — qué fracción del inventario publicado está convirtiendo —, no el volumen de ventas. Para intensidad de ventas (cuánto vendió cada listing) habría que sumar <code style="background:#0d1117;padding:1px 5px;border-radius:3px;color:#79c0ff;">ORDERS_LAST_30DAYS</code>, que no está incluido en este dashboard.
          </div>
        </div>

        <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px;">
          <div style="font-size:13px;font-weight:700;color:#e3b341;margin-bottom:7px;">¿Cómo se eligen los dominios que se muestran por categoría?</div>
          <div style="font-size:13px;color:#8b949e;line-height:1.7;">
            Se muestran los <strong style="color:#c9d1d9;">30 dominios con más Listings Live</strong> dentro de cada AGG1. En categorías con cientos de dominios de cola larga (ej. Cars & Vans), esos 30 concentran la gran mayoría del volumen.
          </div>
        </div>

        <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px;">
          <div style="font-size:13px;font-weight:700;color:#e3b341;margin-bottom:7px;">¿Qué significa Free Shipping aquí?</div>
          <div style="font-size:13px;color:#8b949e;line-height:1.7;">
            Con Free Shipping = listings que tienen el beneficio de envío gratis activo al momento del PHOTO_DATE. En Argentina corresponde al plan <strong style="color:#c9d1d9;">FULFILLMENT (FBM)</strong> o sellers que activan FS por costo propio. No incluye envíos pagos con descuento ni promociones temporales de envío.
          </div>
        </div>

      </div>
    </div>

    <div>
      <div class="section-head">
        <div class="s-bar" style="background:#3fb950"></div>
        <span class="s-title">Fuentes de datos</span>
      </div>
      <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px;display:flex;flex-direction:column;gap:10px;">
        <div style="display:flex;gap:14px;align-items:baseline;">
          <span style="font-size:12px;font-weight:700;color:#3fb950;min-width:220px;">BT_LIVE_LISTINGS_MLA</span>
          <span style="font-size:12px;color:#8b949e;">Fuente de este dashboard. Foto diaria de listings activos con ORDERS_LAST_30DAYS precalculado.</span>
        </div>
      </div>
    </div>

  </div>
</div>
</div>

<div class="footer">
  MercadoLibre Planning &nbsp;·&nbsp; BT_LIVE_LISTINGS_MLA &nbsp;·&nbsp; D-1 &nbsp;·&nbsp; Actualización semanal
</div>

<script>
// @@DASHBOARD_DATA_START@@
const RANGES = __RANGES_JSON__;
const CATEGORY_ORDER = __CATEGORY_ORDER_JSON__;
const CATEGORIES = __CATEGORIES_JSON__;
const SAN_MARTIN = __SAN_MARTIN_JSON__;
// @@DASHBOARD_DATA_END@@

let currentCat = CATEGORY_ORDER[0];

// ─── HELPERS ─────────────────────────────────────────────────────────────────
function fmt(n) {
  if (n == null) return '—';
  if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return Math.round(n/1e3) + 'K';
  return n.toLocaleString('es-AR');
}

function convBg(c, maxC) {
  if (!c || c === 0) return '';
  const t = Math.min(c / maxC, 1);
  const alpha = 0.1 + t * 0.65;
  return `background:rgba(63,185,80,${alpha.toFixed(2)});color:${t > 0.5 ? '#d2f4d3' : '#c9d1d9'}`;
}

function maxConv(d) {
  let m = 0;
  RANGES.forEach(r => {
    const row = d[r]; if (!row) return;
    if (row.con && row.con.c > m) m = row.con.c;
    if (row.sin && row.sin.c > m) m = row.sin.c;
  });
  return m || 1;
}

function totalsOf(d) {
  let tl=0, ts=0, tst=0, cl=0;
  RANGES.forEach(r => {
    const row = d[r]; if (!row) return;
    if (row.con) { tl+=row.con.l; ts+=row.con.s; tst+=row.con.st; cl+=row.con.l; }
    if (row.sin) { tl+=row.sin.l; ts+=row.sin.s; tst+=row.sin.st; }
  });
  return { l:tl, s:ts, st:tst, conv:tl?(ts/tl*100):0, pctFS:tl?(cl/tl*100):0 };
}

// ─── STAT TILES ──────────────────────────────────────────────────────────────
function renderStats(id, d) {
  const t = totalsOf(d);
  document.getElementById(id).innerHTML = `
    <div class="tile">
      <div class="tile-label">Total Listings Live</div>
      <div class="tile-value">${fmt(t.l)}</div>
      <div class="tile-sub">Al __PHOTO_DATE__</div>
    </div>
    <div class="tile">
      <div class="tile-label">Successful (30d)</div>
      <div class="tile-value">${fmt(t.s)}</div>
      <div class="tile-sub">Con ≥ 1 orden en 30 días</div>
    </div>
    <div class="tile">
      <div class="tile-label">SL/LL General</div>
      <div class="tile-value">${t.conv.toFixed(1)}%</div>
      <div class="tile-sub">Successful / Listings</div>
    </div>
    <div class="tile">
      <div class="tile-label">Con Free Shipping</div>
      <div class="tile-value">${t.pctFS.toFixed(1)}%</div>
      <div class="tile-sub">Del total de listings</div>
    </div>`;
}

// ─── TABLE ───────────────────────────────────────────────────────────────────
function renderTable(id, d) {
  const mc = maxConv(d);

  let conL = 0, sinL = 0;
  RANGES.forEach(r => {
    const row = d[r]; if (!row) return;
    if (row.con) conL += row.con.l;
    if (row.sin) sinL += row.sin.l;
  });
  const tot = conL + sinL;
  const pctCon = tot ? (conL/tot*100).toFixed(1) : '0.0';
  const pctSin = tot ? (sinL/tot*100).toFixed(1) : '0.0';

  let h = `<thead>
    <tr>
      <th class="col-range" rowspan="2">Rango ASP (ARS)</th>
      <th class="col-range" rowspan="2" style="text-align:right !important" title="Listings (Con+Sin FS) de este rango">Total LL</th>
      <th class="col-range" rowspan="2" style="text-align:right !important" title="Listings (Con+Sin FS) de este rango sobre el total general">% del total</th>
      <th class="grp-con" colspan="6">🟢 Con Free Shipping <span style="background:rgba(63,185,80,0.15);color:#3fb950;font-size:10px;padding:1px 7px;border-radius:10px;margin-left:6px;font-weight:700">${pctCon}%</span></th>
      <th class="grp-sin" colspan="6">⬜ Sin Free Shipping <span style="background:rgba(118,131,144,0.15);color:#8b949e;font-size:10px;padding:1px 7px;border-radius:10px;margin-left:6px;font-weight:700">${pctSin}%</span></th>
    </tr>
    <tr>
      <th class="grp-con">Listings</th><th class="grp-con" title="% del total Con FS">% grupo</th><th class="grp-con" title="% de listings Con FS en este tramo">% tramo</th><th class="grp-con">Succ.</th>
      <th class="grp-con">SL/LL</th><th class="grp-con">Stock</th>
      <th class="grp-sin">Listings</th><th class="grp-sin" title="% del total Sin FS">% grupo</th><th class="grp-sin" title="% de listings Sin FS en este tramo">% tramo</th><th class="grp-sin">Succ.</th>
      <th class="grp-sin">SL/LL</th><th class="grp-sin">Stock</th>
    </tr>
  </thead><tbody>`;

  RANGES.forEach(r => {
    const row = d[r]; if (!row) return;
    const lbl = r.replace(/^\d+\.\s/, '');
    const con = row.con, sin = row.sin;
    const rowTotal = (con ? con.l : 0) + (sin ? sin.l : 0);
    const pCgrp = con && conL    ? (con.l/conL*100).toFixed(1)    : null;
    const pSgrp = sin && sinL    ? (sin.l/sinL*100).toFixed(1)    : null;
    const pCtrm = con && rowTotal ? (con.l/rowTotal*100).toFixed(1) : null;
    const pStrm = sin && rowTotal ? (sin.l/rowTotal*100).toFixed(1) : null;
    const pRowTot = tot ? (rowTotal/tot*100).toFixed(1) : '0.0';
    const pctStyle = 'color:#8b949e;font-size:11px';
    h += `<tr>
      <td class="col-range">${lbl}</td>
      <td style="font-weight:600;color:#e6edf3">${fmt(rowTotal)}</td>
      <td style="font-weight:600;color:#e6edf3">${pRowTot}%</td>
      ${con
        ? `<td class="con-first">${fmt(con.l)}</td>
           <td style="${pctStyle}">${pCgrp}%</td>
           <td style="${pctStyle}">${pCtrm}%</td>
           <td>${fmt(con.s)}</td>
           <td class="conv con-first" style="${convBg(con.c,mc)}">${con.c.toFixed(1)}%</td>
           <td>${fmt(con.st)}</td>`
        : `<td class="con-first empty">—</td><td class="empty">—</td><td class="empty">—</td><td class="empty">—</td>
           <td class="conv con-first empty">—</td><td class="empty">—</td>`}
      ${sin
        ? `<td class="sin-first">${fmt(sin.l)}</td>
           <td style="${pctStyle}">${pSgrp}%</td>
           <td style="${pctStyle}">${pStrm}%</td>
           <td>${fmt(sin.s)}</td>
           <td class="conv sin-first" style="${convBg(sin.c,mc)}">${sin.c.toFixed(1)}%</td>
           <td>${fmt(sin.st)}</td>`
        : `<td class="sin-first empty">—</td><td class="empty">—</td><td class="empty">—</td><td class="empty">—</td>
           <td class="conv sin-first empty">—</td><td class="empty">—</td>`}
    </tr>`;
  });

  let tc={l:0,s:0,st:0}, ts={l:0,s:0,st:0};
  RANGES.forEach(r => {
    const row = d[r]; if (!row) return;
    if (row.con){tc.l+=row.con.l;tc.s+=row.con.s;tc.st+=row.con.st;}
    if (row.sin){ts.l+=row.sin.l;ts.s+=row.sin.s;ts.st+=row.sin.st;}
  });
  h += `</tbody><tfoot><tr>
    <td class="col-range">TOTAL</td>
    <td style="font-weight:700;color:#e6edf3">${fmt(tc.l+ts.l)}</td>
    <td style="font-weight:700;color:#e6edf3">100%</td>
    ${(()=>{ const gt=tc.l+ts.l; const ps='color:#8b949e;font-size:11px'; return `
    <td class="con-first">${fmt(tc.l)}</td>
    <td style="${ps}">100%</td>
    <td style="${ps}">${gt?(tc.l/gt*100).toFixed(1):0}%</td>
    <td>${fmt(tc.s)}</td>
    <td class="conv con-first">${tc.l?(tc.s/tc.l*100).toFixed(1):0}%</td><td>${fmt(tc.st)}</td>
    <td class="sin-first">${fmt(ts.l)}</td>
    <td style="${ps}">100%</td>
    <td style="${ps}">${gt?(ts.l/gt*100).toFixed(1):0}%</td>
    <td>${fmt(ts.s)}</td>
    <td class="conv sin-first">${ts.l?(ts.s/ts.l*100).toFixed(1):0}%</td><td>${fmt(ts.st)}</td>`;})()}
  </tr></tfoot>`;

  document.getElementById(id).innerHTML = h;
}

function setCount(id, d) {
  const t = totalsOf(d);
  document.getElementById(id).innerHTML = `${fmt(t.l)} listings &nbsp;·&nbsp; SL/LL ${t.conv.toFixed(1)}% &nbsp;·&nbsp; FS ${t.pctFS.toFixed(1)}%`;
}

// ─── CARD TOGGLE ─────────────────────────────────────────────────────────────
function toggleCard(head) {
  head.closest('.agg2-card').classList.toggle('open');
}

// ─── TAB SWITCHING ───────────────────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('pane-' + name).classList.add('active');
  btn.classList.add('active');
}

// ─── GLOBAL TOGGLE: PLAN SAN MARTÍN ──────────────────────────────────────────
// While active, this is a whole-page mode: the category picker and the
// per-category tabs (Agrupadores, Dominios, ...) don't apply, so they're
// hidden entirely instead of just sitting next to an unrelated pane.
function toggleSanMartin(btn) {
  const catTabs = document.getElementById('cat-tabs');
  const navTabs = document.querySelector('.nav-tabs');
  const isActive = btn.classList.contains('active');

  if (isActive) {
    btn.classList.remove('active');
    btn.innerHTML = '🚚 Plan San Martín';
    catTabs.classList.remove('hidden');
    navTabs.classList.remove('hidden');
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.getElementById('pane-agrupadores').classList.add('active');
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('.nav-tab[onclick*="agrupadores"]').classList.add('active');
    const cat = CATEGORIES[currentCat];
    if (cat) document.getElementById('header-title').textContent = cat.label + ' — Live Listings Dashboard';
  } else {
    btn.classList.add('active');
    btn.innerHTML = '✕ Volver a categorías';
    catTabs.classList.add('hidden');
    navTabs.classList.add('hidden');
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.getElementById('pane-sanmartin').classList.add('active');
    document.getElementById('header-title').textContent = 'Plan San Martín — Seguimiento 15K a 33K (todas las categorías)';
  }
}

// ─── CATEGORY SWITCHING ──────────────────────────────────────────────────────
function renderCategoryTabs() {
  const el = document.getElementById('cat-tabs');
  el.innerHTML = CATEGORY_ORDER.map(k => {
    const c = CATEGORIES[k];
    return `<button class="cat-tab${k===currentCat?' active':''}" onclick="switchCategory('${k}', this)">${c.label}</button>`;
  }).join('');
}

function switchCategory(key, btn) {
  currentCat = key;
  document.querySelectorAll('.cat-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  loadCategory();
}

function loadCategory() {
  const cat = CATEGORIES[currentCat];

  document.getElementById('header-title').textContent = cat.label + ' — Live Listings Dashboard';
  document.getElementById('agg1-title').textContent = cat.label;
  document.getElementById('agg2-section-pill').textContent = 'Dentro de ' + cat.label;
  document.getElementById('domains-pill').textContent =
    cat.DOMAIN_ORDER.length + ' de ' + cat.totalDomains + ' dominios — top por volumen de listings';

  renderStats('stats-agg1', cat.DATA.agg1);
  renderTable('table-agg1', cat.DATA.agg1);
  renderAgg2Cards(cat);
  renderDomains(cat);
  buildInsights(cat);
  buildPareto(cat);
  const brecha = buildBrecha(cat);
  buildEjecutiva(cat, brecha);
}

// ─── AGG2 CARDS ──────────────────────────────────────────────────────────────
function renderAgg2Cards(cat) {
  const grid = document.getElementById('agg2-grid');
  grid.innerHTML = cat.agg2List.map(a => `
    <div class="agg2-card">
      <div class="agg2-card-head" onclick="toggleCard(this)">
        <div class="s-bar" style="background:${a.color};height:14px;width:3px"></div>
        <span class="agg2-card-title">${a.label}</span>
        <span class="agg2-card-count" id="cnt-${a.key}"></span>
        <span class="agg2-chevron">▼</span>
      </div>
      <div class="agg2-card-body"><div class="table-wrap"><table id="table-${a.key}"></table></div></div>
    </div>`).join('');
  cat.agg2List.forEach(a => {
    renderTable('table-' + a.key, cat.DATA[a.key]);
    setCount('cnt-' + a.key, cat.DATA[a.key]);
  });
}

// ─── DOMAIN RENDERING ────────────────────────────────────────────────────────
function renderDomains(cat) {
  const container = document.getElementById('domains-container');
  container.innerHTML = '';
  cat.DOMAIN_ORDER.forEach(domain => {
    const label  = cat.DOMAIN_LABELS[domain];
    const color  = cat.DOMAIN_COLORS[domain];
    const data   = cat.DD[domain];
    const t      = totalsOf(data);

    const div = document.createElement('div');
    div.className = 'agg2-card';
    div.innerHTML = `
      <div class="agg2-card-head" onclick="toggleCard(this)">
        <div class="s-bar" style="background:${color};height:18px;width:4px"></div>
        <span class="agg2-card-title">${label}</span>
        <span class="agg2-card-sub" style="margin-left:8px">${domain}</span>
        <span class="agg2-card-count">${fmt(t.l)} listings &nbsp;·&nbsp; SL/LL ${t.conv.toFixed(1)}% &nbsp;·&nbsp; FS ${t.pctFS.toFixed(1)}%</span>
        <span class="agg2-chevron">▼</span>
      </div>
      <div class="agg2-card-body"><div class="table-wrap"><table id="table-dom-${domain}"></table></div></div>
    `;
    container.appendChild(div);
    renderTable('table-dom-' + domain, data);
  });
}

// ─── INSIGHTS ENGINE ─────────────────────────────────────────────────────────
function buildInsights(cat) {
  const AGG_SOURCES = [
    { key:'agg1', label: cat.label + ' (Total)', color:'#ffe600' },
    ...cat.agg2List.map(a => ({ key:a.key, label:a.label + ' (AGG2)', color:a.color })),
  ];

  const DOMAIN_SOURCES = cat.DOMAIN_ORDER.map(k => ({
    key: k, label: cat.DOMAIN_LABELS[k], color: cat.DOMAIN_COLORS[k], data: cat.DD[k]
  }));

  const ALL_SOURCES = [
    ...AGG_SOURCES.map(a => ({ ...a, data: cat.DATA[a.key] })),
    ...DOMAIN_SOURCES
  ];

  const RANGE_LABELS = {
    '01. Hasta 5K':'Hasta $5K','02. 5K a 15K':'$5K–15K','03. 15K a 33K':'$15K–33K',
    '04. 33K a 50K':'$33K–50K','05. 50K a 75K':'$50K–75K','06. 75K a 90K':'$75K–90K',
    '07. 90K a 120K':'$90K–120K','08. 120K a 150K':'$120K–150K',
    '09. 150K a 175K':'$150K–175K','10. 175K a 220K':'$175K–220K',
    '11. 220K a 250K':'$220K–250K','12. 250K a 300K':'$250K–300K',
    '13. 300K a 450K':'$300K–450K','14. 450K a 600K':'$450K–600K',
    '15. 600K a 1M':'$600K–1M','16. Mas de 1M':'Más de $1M'
  };

  function rl(r) { return RANGE_LABELS[r] || r; }

  function demandScore(conv, listings) {
    if (!conv || conv < 5 || !listings || listings < 10) return 0;
    return conv / Math.max(1, Math.log10(listings) - 0.5);
  }

  function fsScore(sinConv, sinL, conL) {
    if (!sinConv || sinConv < 3 || !sinL || sinL < 300) return 0;
    const gap = Math.log10(sinL / Math.max(1, conL || 0) + 1);
    return sinConv * gap;
  }

  function satScore(conv, listings) {
    if (!listings || listings < 8000) return 0;
    if (conv > 2) return 0;
    return listings * (1 - conv / 10);
  }

  const demand = [], fsAct = [], sat = [];

  ALL_SOURCES.forEach(src => {
    RANGES.forEach(r => {
      const row = src.data[r]; if (!row) return;
      const con = row.con, sin = row.sin;

      if (con && con.c >= 5) {
        const sc = demandScore(con.c, con.l);
        if (sc > 0) demand.push({
          label: src.label, color: src.color, range: r,
          conv: con.c, listings: con.l, score: sc,
          why: `${con.c}% SL/LL con ${con.l.toLocaleString('es-AR')} listings Con FS`
        });
      }

      if (sin && sin.c >= 3 && sin.l >= 300 && r !== '01. Hasta 5K' && r !== '02. 5K a 15K') {
        const conL = (con && con.l) || 0;
        const conPct = conL / sin.l;
        if (conPct < 0.15) {
          const sc = fsScore(sin.c, sin.l, conL);
          if (sc > 0) fsAct.push({
            label: src.label, color: src.color, range: r,
            sinConv: sin.c, sinL: sin.l, conL,
            score: sc,
            why: `${sin.l.toLocaleString('es-AR')} listings Sin FS al ${sin.c}% conv vs solo ${conL.toLocaleString('es-AR')} Con FS`
          });
        }
      }

      if (con && con.l >= 8000 && con.c < 2) {
        const sc = satScore(con.c, con.l);
        if (sc > 0) sat.push({
          label: src.label, color: src.color, range: r,
          conv: con.c, listings: con.l, score: sc,
          why: `${con.l.toLocaleString('es-AR')} listings Con FS con solo ${con.c}% SL/LL`
        });
      }
    });
  });

  demand.sort((a,b) => b.score - a.score);
  fsAct.sort((a,b)  => b.score - a.score);
  sat.sort((a,b)    => b.score - a.score);

  function renderPanel(elId, items, renderFn) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = items.slice(0,8).map((d,i) => renderFn(d, i+1)).join('');
  }

  renderPanel('ins-demand', demand, (d,i) => `
    <div class="ins-item">
      <div class="ins-item-top">
        <span class="ins-rank">${i}</span>
        <span class="ins-cat" style="color:${d.color}">${d.label}</span>
      </div>
      <span class="ins-range">${rl(d.range)}</span>
      <div class="ins-metrics">
        <span class="ins-m hi">SL/LL ${d.conv}%</span>
        <span class="ins-m muted">${d.listings.toLocaleString('es-AR')} listings</span>
      </div>
      <div class="ins-why">${d.why}</div>
    </div>`);

  renderPanel('ins-fs', fsAct, (d,i) => `
    <div class="ins-item">
      <div class="ins-item-top">
        <span class="ins-rank">${i}</span>
        <span class="ins-cat" style="color:${d.color}">${d.label}</span>
      </div>
      <span class="ins-range">${rl(d.range)}</span>
      <div class="ins-metrics">
        <span class="ins-m mid">Sin FS ${d.sinConv}% conv</span>
        <span class="ins-m muted">Con FS: ${d.conL.toLocaleString('es-AR')}</span>
      </div>
      <div class="ins-why">${d.why}</div>
    </div>`);

  renderPanel('ins-sat', sat, (d,i) => `
    <div class="ins-item">
      <div class="ins-item-top">
        <span class="ins-rank">${i}</span>
        <span class="ins-cat" style="color:${d.color}">${d.label}</span>
      </div>
      <span class="ins-range">${rl(d.range)}</span>
      <div class="ins-metrics">
        <span class="ins-m lo">SL/LL ${d.conv}%</span>
        <span class="ins-m muted">${d.listings.toLocaleString('es-AR')} listings</span>
      </div>
      <div class="ins-why">${d.why}</div>
    </div>`);

  const domEl = document.getElementById('ins-domains');
  if (domEl) {
    domEl.innerHTML = DOMAIN_SOURCES.map(src => {
      let bestD = null, bestDsc = 0;
      let bestFS = null, bestFSsc = 0;
      let worstSat = null, worstSatSc = 0;

      RANGES.forEach(r => {
        const row = src.data[r]; if (!row) return;
        const con = row.con, sin = row.sin;
        if (con && con.c >= 5) {
          const sc = demandScore(con.c, con.l);
          if (sc > bestDsc) { bestDsc = sc; bestD = { r, conv: con.c, l: con.l }; }
        }
        if (sin && sin.c >= 3 && sin.l >= 200 && r !== '01. Hasta 5K' && r !== '02. 5K a 15K') {
          const conL = (con && con.l) || 0;
          if (conL / sin.l < 0.2) {
            const sc = fsScore(sin.c, sin.l, conL);
            if (sc > bestFSsc) { bestFSsc = sc; bestFS = { r, sinConv: sin.c, sinL: sin.l, conL }; }
          }
        }
        if (con && con.l >= 5000 && con.c < 2) {
          const sc = satScore(con.c, con.l);
          if (sc > worstSatSc) { worstSatSc = sc; worstSat = { r, conv: con.c, l: con.l }; }
        }
      });

      const rows = [];
      if (bestD) rows.push(`
        <div class="dom-ins-row">
          <span class="dom-ins-badge g">OPORTUNIDAD</span>
          <span><strong>${rl(bestD.r)}</strong> → ${bestD.conv}% SL/LL con ${bestD.l.toLocaleString('es-AR')} listings Con FS</span>
        </div>`);
      if (bestFS) rows.push(`
        <div class="dom-ins-row">
          <span class="dom-ins-badge y">ACTIVAR FS</span>
          <span><strong>${rl(bestFS.r)}</strong> → ${bestFS.sinL.toLocaleString('es-AR')} Sin FS al ${bestFS.sinConv}% conv · solo ${bestFS.conL.toLocaleString('es-AR')} Con FS</span>
        </div>`);
      if (worstSat) rows.push(`
        <div class="dom-ins-row">
          <span class="dom-ins-badge r">SATURADO</span>
          <span><strong>${rl(worstSat.r)}</strong> → ${worstSat.l.toLocaleString('es-AR')} listings Con FS con ${worstSat.conv}% SL/LL</span>
        </div>`);
      if (rows.length === 0) rows.push(`<div class="dom-ins-row"><span class="ins-m muted">Sin señales destacadas en este dominio</span></div>`);

      return `
        <div class="dom-ins-card">
          <div class="dom-ins-title">
            <span class="dom-ins-dot" style="background:${src.color}"></span>
            ${src.label}
          </div>
          ${rows.join('')}
        </div>`;
    }).join('');
  }

  const pill = document.getElementById('ins-pill');
  if (pill) pill.textContent = `${demand.length} oportunidades de demanda · ${fsAct.length} de activación FS · ${sat.length} saturados detectados`;
}

// ─── REGLA 80/20 ─────────────────────────────────────────────────────────────
function buildPareto(cat) {
  function rl(r) { return r.replace(/^\d+\.\s*/, ''); }

  const domPareto = cat.DOMAIN_ORDER.map(k => {
    const ranges = cat.DD[k];
    if (!ranges) return null;
    const rangeData = RANGES.map(r => {
      const d = ranges[r]; if (!d) return { r, sl: 0 };
      const sl = ((d.con && d.con.s) || 0) + ((d.sin && d.sin.s) || 0);
      return { r, sl };
    }).filter(x => x.sl > 0);

    if (rangeData.length === 0) return null;

    const totalSL = rangeData.reduce((a, b) => a + b.sl, 0);
    rangeData.sort((a, b) => b.sl - a.sl);

    let cum = 0, cutoffIdx = rangeData.length - 1;
    for (let i = 0; i < rangeData.length; i++) {
      cum += rangeData[i].sl;
      if (cum / totalSL >= 0.80) { cutoffIdx = i; break; }
    }
    const rangesFor80 = cutoffIdx + 1;
    const maxSL = rangeData[0].sl;

    return {
      key: k,
      label: cat.DOMAIN_LABELS[k] || k,
      color: cat.DOMAIN_COLORS[k] || '#8b949e',
      totalSL, rangeData, cutoffIdx, rangesFor80, maxSL
    };
  }).filter(Boolean);

  const globalTotalSL = domPareto.reduce((a, d) => a + d.totalSL, 0);
  const avgRanges = domPareto.length > 0
    ? (domPareto.reduce((a, d) => a + d.rangesFor80, 0) / domPareto.length).toFixed(1)
    : '—';
  const mostConcentrated = [...domPareto].sort((a, b) => a.rangesFor80 - b.rangesFor80)[0];
  const mostDispersed    = [...domPareto].sort((a, b) => b.rangesFor80 - a.rangesFor80)[0];

  const pill = document.getElementById('pareto-pill');
  if (pill) pill.textContent = `${domPareto.length} dominios · promedio ${avgRanges} tramos para el 80% de SL`;

  const tilesEl = document.getElementById('pareto-tiles');
  if (tilesEl) {
    tilesEl.innerHTML = `
      <div class="tile">
        <div class="tile-label">SL Total del portfolio</div>
        <div class="tile-value" style="color:#3fb950">${fmt(globalTotalSL)}</div>
        <div class="tile-sub">Suma de todos los dominios</div>
      </div>
      <div class="tile">
        <div class="tile-label">Promedio de tramos para el 80%</div>
        <div class="tile-value" style="color:#e3b341">${avgRanges}</div>
        <div class="tile-sub">Por dominio</div>
      </div>
      <div class="tile">
        <div class="tile-label">Más concentrado</div>
        <div class="tile-value" style="color:#3fb950;font-size:16px;margin-top:4px">${mostConcentrated ? mostConcentrated.label : '—'}</div>
        <div class="tile-sub">${mostConcentrated ? mostConcentrated.rangesFor80 + ' tramo(s) hacen el 80%' : ''}</div>
      </div>
      <div class="tile">
        <div class="tile-label">Más disperso</div>
        <div class="tile-value" style="color:#f85149;font-size:16px;margin-top:4px">${mostDispersed ? mostDispersed.label : '—'}</div>
        <div class="tile-sub">${mostDispersed ? mostDispersed.rangesFor80 + ' tramos para el 80%' : ''}</div>
      </div>`;
  }

  const gridEl = document.getElementById('pareto-grid');
  if (!gridEl) return;

  const sorted = [...domPareto].sort((a, b) => a.rangesFor80 - b.rangesFor80);

  gridEl.innerHTML = sorted.map(d => {
    const badge = d.rangesFor80 <= 2
      ? `<span class="pareto-card-badge concentrated">${d.rangesFor80} tramo${d.rangesFor80 > 1 ? 's' : ''} = 80%</span>`
      : d.rangesFor80 <= 4
        ? `<span class="pareto-card-badge mid">${d.rangesFor80} tramos = 80%</span>`
        : `<span class="pareto-card-badge dispersed">${d.rangesFor80} tramos = 80%</span>`;

    let cumSL = 0;
    const rows = d.rangeData.map((item, i) => {
      const prevCum = cumSL;
      cumSL += item.sl;
      const isIn80 = i <= d.cutoffIdx;
      const barW = d.maxSL > 0 ? (item.sl / d.maxSL * 100).toFixed(1) : 0;
      const pctOfTotal = d.totalSL > 0 ? (item.sl / d.totalSL * 100).toFixed(1) : 0;
      const cumPct = d.totalSL > 0 ? (cumSL / d.totalSL * 100).toFixed(0) : 0;

      let cutoffHtml = '';
      if (i === d.cutoffIdx) {
        cutoffHtml = `<div class="pareto-cutoff"><div style="flex:1;height:1px;background:rgba(227,179,65,0.4)"></div><div class="pareto-cutoff-label">↑ ${cumPct}% del SL acumulado</div><div style="flex:1;height:1px;background:rgba(227,179,65,0.4)"></div></div>`;
      }

      return `
        <div class="pareto-row">
          <div class="pareto-range">${rl(item.r)}</div>
          <div class="pareto-bar-wrap">
            <div class="pareto-bar-fill ${isIn80 ? 'in80' : 'out80'}" style="width:${barW}%"></div>
          </div>
          <div class="pareto-sl-val">${fmt(item.sl)}</div>
          <div class="pareto-pct-val">${pctOfTotal}%</div>
        </div>${cutoffHtml}`;
    }).join('');

    const top1Pct = d.totalSL > 0 ? (d.rangeData[0].sl / d.totalSL * 100).toFixed(0) : 0;
    const top1Range = rl(d.rangeData[0].r);

    return `
      <div class="pareto-card">
        <div class="pareto-card-head">
          <span class="dom-ins-dot" style="background:${d.color};width:9px;height:9px;border-radius:50%;flex-shrink:0"></span>
          <span class="pareto-card-name">${d.label}</span>
          ${badge}
        </div>
        <div class="pareto-card-body">${rows}</div>
        <div class="pareto-summary">
          El tramo <strong>${top1Range}</strong> solo genera el <strong>${top1Pct}%</strong> del total de SL
          · ${fmt(d.totalSL)} SL en total
        </div>
      </div>`;
  }).join('');
}

// ─── BRECHA DE CONVERSIÓN ────────────────────────────────────────────────────
function buildBrecha(cat) {
  const domStats = cat.DOMAIN_ORDER.map(k => {
    let ll = 0, sl = 0;
    const ranges = cat.DD[k];
    if (!ranges) return { key: k, label: cat.DOMAIN_LABELS[k] || k, color: cat.DOMAIN_COLORS[k] || '#8b949e', ll: 0, sl: 0, gap: 0, pct: 0 };
    RANGES.forEach(r => {
      const d = ranges[r];
      if (!d) return;
      if (d.con) { ll += d.con.l || 0; sl += d.con.s || 0; }
      if (d.sin) { ll += d.sin.l || 0; sl += d.sin.s || 0; }
    });
    const gap = ll - sl;
    const pct = ll > 0 ? (sl / ll * 100) : 0;
    return { key: k, label: cat.DOMAIN_LABELS[k] || k, color: cat.DOMAIN_COLORS[k] || '#8b949e', ll, sl, gap, pct };
  }).filter(d => d.ll > 0);

  let totalLL = 0, totalSL = 0;
  RANGES.forEach(r => {
    const d = cat.DATA.agg1[r];
    if (!d) return;
    if (d.con) { totalLL += d.con.l || 0; totalSL += d.con.s || 0; }
    if (d.sin) { totalLL += d.sin.l || 0; totalSL += d.sin.s || 0; }
  });
  const totalGap = totalLL - totalSL;
  const globalPct = totalLL > 0 ? (totalSL / totalLL * 100) : 0;

  const tilesEl = document.getElementById('brecha-tiles');
  if (tilesEl) {
    tilesEl.innerHTML = `
      <div class="tile">
        <div class="tile-label">Total Live Listings</div>
        <div class="tile-value">${fmt(totalLL)}</div>
        <div class="tile-sub">Con + Sin FS · Todos los dominios</div>
      </div>
      <div class="tile">
        <div class="tile-label">Successful Listings (SL)</div>
        <div class="tile-value" style="color:#3fb950">${fmt(totalSL)}</div>
        <div class="tile-sub">Al menos 1 orden en últimos 30 días</div>
      </div>
      <div class="tile">
        <div class="tile-label">SL/LL% Global</div>
        <div class="tile-value" style="color:${globalPct >= 5 ? '#3fb950' : globalPct >= 2 ? '#e3b341' : '#f85149'}">${globalPct.toFixed(1)}%</div>
        <div class="tile-sub">Tasa de conversión global</div>
      </div>
      <div class="tile">
        <div class="tile-label">Listings sin convertir</div>
        <div class="tile-value" style="color:#f85149">${fmt(totalGap)}</div>
        <div class="tile-sub">${(100 - globalPct).toFixed(1)}% no vendió nada en 30 días</div>
      </div>`;
  }

  const pill = document.getElementById('brecha-pill');
  if (pill) pill.textContent = `${domStats.length} dominios analizados · SL/LL global ${globalPct.toFixed(1)}%`;

  const sorted = [...domStats].sort((a, b) => b.gap - a.gap);

  const barsEl = document.getElementById('brecha-bars');
  if (barsEl) {
    barsEl.innerHTML = sorted.map(d => {
      const slPct = d.ll > 0 ? (d.sl / d.ll * 100) : 0;
      const gapPct = 100 - slPct;
      return `
        <div class="brecha-bar-row">
          <div class="brecha-label" title="${d.label}">${d.label}</div>
          <div class="brecha-bars">
            <div class="brecha-bar-sl" style="width:${slPct.toFixed(1)}%"></div>
            <div class="brecha-bar-gap" style="left:${slPct.toFixed(1)}%;width:${gapPct.toFixed(1)}%"></div>
          </div>
          <div class="brecha-pct-sl">${slPct.toFixed(1)}%</div>
          <div class="brecha-pct-gap">−${gapPct.toFixed(1)}%</div>
          <div class="brecha-nums">${fmt(d.sl)} / ${fmt(d.ll)}</div>
        </div>`;
    }).join('');
  }

  const tableEl = document.getElementById('brecha-table');
  if (tableEl) {
    const rows = sorted.map((d, i) => {
      const slPct = d.ll > 0 ? (d.sl / d.ll * 100) : 0;
      const color = slPct >= 5 ? '#3fb950' : slPct >= 2 ? '#e3b341' : '#f85149';
      return `<tr>
        <td style="text-align:left;font-weight:700;color:${d.color}">${d.label}</td>
        <td>${fmt(d.ll)}</td>
        <td style="color:#3fb950">${fmt(d.sl)}</td>
        <td style="color:#f85149">${fmt(d.gap)}</td>
        <td class="conv" style="color:${color}">${slPct.toFixed(1)}%</td>
      </tr>`;
    }).join('');
    tableEl.innerHTML = `
      <thead>
        <tr>
          <th style="text-align:left;background:#1c2128;padding:9px 10px;font-size:11px;font-weight:700;text-transform:uppercase;border-bottom:1px solid #30363d">Dominio</th>
          <th style="background:#1c2128;padding:9px 10px;font-size:11px;font-weight:700;text-transform:uppercase;border-bottom:1px solid #30363d;text-align:right">LL Total</th>
          <th style="background:#1c2128;padding:9px 10px;font-size:11px;font-weight:700;text-transform:uppercase;border-bottom:1px solid #30363d;text-align:right;color:#3fb950">SL</th>
          <th style="background:#1c2128;padding:9px 10px;font-size:11px;font-weight:700;text-transform:uppercase;border-bottom:1px solid #30363d;text-align:right;color:#f85149">Gap (no conv.)</th>
          <th style="background:#1c2128;padding:9px 10px;font-size:11px;font-weight:700;text-transform:uppercase;border-bottom:2px solid #30363d;text-align:right">SL/LL%</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>`;
  }

  return { domStats, sorted, totalLL, totalSL, totalGap, globalPct };
}

// ─── VISTA EJECUTIVA ─────────────────────────────────────────────────────────
function buildEjecutiva(cat, b) {
  if (!b) return;
  const { sorted, totalLL, totalSL, totalGap, globalPct } = b;
  const noConvPct = (100 - globalPct).toFixed(1);

  const heroEl = document.getElementById('exec-hero');
  if (heroEl) {
    heroEl.innerHTML = `
      <div class="exec-hero-headline">El ${noConvPct}% de los listings<br>no vendió nada en los últimos 30 días</div>
      <div class="exec-hero-sub">Sobre un universo de <strong style="color:#e6edf3">${fmt(totalLL)}</strong> listings activos en ${cat.label}</div>`;
  }

  const kpisEl = document.getElementById('exec-kpis');
  if (kpisEl) {
    const topDomain = sorted[0];
    const bestDomain = [...b.domStats].sort((a, b) => b.pct - a.pct)[0];
    kpisEl.innerHTML = `
      <div class="exec-kpi">
        <div class="exec-kpi-val" style="color:#f85149">${fmt(totalGap)}</div>
        <div class="exec-kpi-label">Listings sin una sola orden</div>
        <div class="exec-kpi-note">En los últimos 30 días</div>
      </div>
      <div class="exec-kpi">
        <div class="exec-kpi-val" style="color:#e3b341">${topDomain ? topDomain.label : '—'}</div>
        <div class="exec-kpi-label">Dominio con mayor brecha absoluta</div>
        <div class="exec-kpi-note">${topDomain ? fmt(topDomain.gap) + ' listings sin convertir' : ''}</div>
      </div>
      <div class="exec-kpi">
        <div class="exec-kpi-val" style="color:#3fb950">${bestDomain ? bestDomain.pct.toFixed(1) + '%' : '—'}</div>
        <div class="exec-kpi-label">Mejor SL/LL% del portfolio</div>
        <div class="exec-kpi-note">${bestDomain ? bestDomain.label : ''}</div>
      </div>`;
  }

  const top5El = document.getElementById('exec-top5');
  if (top5El) {
    const top5 = sorted.slice(0, 5);
    const maxGap = top5[0]?.gap || 1;
    top5El.innerHTML = top5.map((d, i) => {
      const barW = (d.gap / maxGap * 100).toFixed(1);
      const gapPct = d.ll > 0 ? (d.gap / d.ll * 100) : 0;
      return `
        <div class="exec-top-row">
          <div class="exec-rank">${i + 1}</div>
          <div class="exec-dom-name" style="color:${d.color}">${d.label}</div>
          <div class="exec-gap-bar-wrap">
            <div class="exec-gap-bar" style="width:${barW}%"></div>
          </div>
          <div class="exec-gap-pct">${gapPct.toFixed(1)}% gap</div>
          <div class="exec-gap-abs">${fmt(d.gap)} sin conv.</div>
        </div>`;
    }).join('');
  }

  const actionsEl = document.getElementById('exec-actions');
  if (actionsEl) {
    const topDemand = [...b.domStats].filter(d => d.ll > 5000).sort((a, b) => b.pct - a.pct)[0];
    const worst = sorted[0];
    const potential = sorted.filter(d => d.pct >= 1 && d.pct < 5 && d.ll > 10000).sort((a, b) => b.gap - a.gap)[0] || sorted[1];

    actionsEl.innerHTML = `
      <div class="exec-action-title">Acciones recomendadas</div>
      <div class="exec-action-item">
        <div class="exec-action-num">1</div>
        <div class="exec-action-text">
          <strong>Activar Free Shipping en ${topDemand ? topDemand.label : 'dominios clave'}</strong><br>
          Es el dominio con mayor tasa de conversión (${topDemand ? topDemand.pct.toFixed(1) + '%' : '—'} SL/LL).
          Priorizar sellers sin FS para escalar la base de listings que convierten.
        </div>
      </div>
      <div class="exec-action-item">
        <div class="exec-action-num">2</div>
        <div class="exec-action-text">
          <strong>Intervenir ${worst ? worst.label : 'dominio crítico'} — ${worst ? fmt(worst.gap) : '—'} listings sin una sola venta</strong><br>
          Es el dominio con la mayor brecha absoluta del portfolio. Revisar pricing, fotos y descripción con sellers activos.
        </div>
      </div>
      <div class="exec-action-item">
        <div class="exec-action-num">3</div>
        <div class="exec-action-text">
          <strong>Desarrollar ${potential ? potential.label : 'dominios con potencial'} con SL/LL actual de ${potential ? potential.pct.toFixed(1) + '%' : '—'}</strong><br>
          Categoría con alto volumen de listings y conversión aún baja. Doble palanca: mejorar listings existentes + atraer nuevos sellers con propuesta de valor.
        </div>
      </div>`;
  }
}

// ─── PLAN SAN MARTÍN ─────────────────────────────────────────────────────────
function smCell(cell) {
  return cell ? { l: cell.l, s: cell.s, c: cell.c, st: cell.st } : { l: 0, s: 0, c: 0, st: 0 };
}

let smTableCounter = 0;

function renderSanMartinTable(id, monthly, months) {
  let rows = '';
  months.forEach(m => {
    const cell = monthly[m] || { con: null, sin: null };
    const con = smCell(cell.con), sin = smCell(cell.sin);
    const totalL = con.l + sin.l;
    const pctCon = totalL ? (con.l / totalL * 100) : null;
    const barColor = pctCon == null ? '#30363d' : pctCon >= 66 ? '#3fb950' : pctCon >= 33 ? '#e3b341' : '#f85149';
    rows += `<tr>
      <td class="col-range">${m}</td>
      <td class="con-first">${fmt(con.l)}</td>
      <td>${fmt(con.s)}</td>
      <td class="conv" style="${convBg(con.c,30)}">${con.l ? con.c.toFixed(1)+'%' : '—'}</td>
      <td class="sin-first">${fmt(sin.l)}</td>
      <td>${fmt(sin.s)}</td>
      <td class="conv" style="${convBg(sin.c,30)}">${sin.l ? sin.c.toFixed(1)+'%' : '—'}</td>
      <td style="min-width:150px">
        <div style="display:flex;align-items:center;gap:8px;justify-content:flex-end">
          <div class="pareto-bar-wrap" style="width:70px">
            <div class="pareto-bar-fill" style="width:${pctCon==null?0:pctCon.toFixed(1)}%;background:${barColor}"></div>
          </div>
          <span style="font-weight:700;color:${barColor};min-width:44px;text-align:right">${pctCon==null?'—':pctCon.toFixed(1)+'%'}</span>
        </div>
      </td>
    </tr>`;
  });
  document.getElementById(id).innerHTML = `
    <thead>
      <tr>
        <th class="col-range" rowspan="2">Mes</th>
        <th class="grp-con" colspan="3">🟢 Con Free Shipping</th>
        <th class="grp-sin" colspan="3">⬜ Sin Free Shipping</th>
        <th rowspan="2" style="text-align:right !important">% Con FS (15K–33K)</th>
      </tr>
      <tr>
        <th class="grp-con">Listings</th><th class="grp-con">SL</th><th class="grp-con">SL/LL</th>
        <th class="grp-sin">Listings</th><th class="grp-sin">SL</th><th class="grp-sin">SL/LL</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>`;
}

function renderSanMartinNode(container, node, depth) {
  const div = document.createElement('div');
  div.className = 'agg2-card';
  const tableId = 'sm-table-' + (smTableCounter++);
  const months = SAN_MARTIN.months;
  const lastM = months[months.length - 1];
  const prevM = months.length > 1 ? months[months.length - 2] : null;

  function pctConOf(m) {
    const cell = node.monthly[m]; if (!cell) return null;
    const con = smCell(cell.con), sin = smCell(cell.sin);
    const tot = con.l + sin.l;
    return tot ? con.l / tot * 100 : null;
  }

  const lastPct = pctConOf(lastM);
  const prevPct = prevM ? pctConOf(prevM) : null;
  let deltaHtml = '';
  if (lastPct != null && prevPct != null) {
    const d = lastPct - prevPct;
    if (Math.abs(d) < 0.05) {
      deltaHtml = `<span class="sm-delta">● 0.0pp vs mes anterior</span>`;
    } else {
      const cls = d >= 0 ? 'up' : 'down';
      deltaHtml = `<span class="sm-delta ${cls}">${d >= 0 ? '▲' : '▼'} ${Math.abs(d).toFixed(1)}pp vs mes anterior</span>`;
    }
  }
  const badgeColor = lastPct == null ? '#8b949e' : lastPct >= 66 ? '#3fb950' : lastPct >= 33 ? '#e3b341' : '#f85149';
  const hasChildren = node.children && node.children.length > 0;
  // AGG1 (depth 0) and leaf domains always get their own monthly table.
  // AGG2 (depth 1, when it has domain children) is just a folder: the badge
  // above already summarizes it, so opening it goes straight to the domains
  // instead of showing a redundant table first.
  const showOwnTable = depth === 0 || !hasChildren;

  div.innerHTML = `
    <div class="agg2-card-head" onclick="toggleCard(this)">
      <div class="s-bar" style="background:${node.color};height:16px;width:3px"></div>
      <span class="agg2-card-title" style="font-size:${depth === 0 ? '14px' : '13px'}">${node.label}</span>
      <span class="sm-badge-pct" style="background:${badgeColor}22;color:${badgeColor}">${lastPct != null ? lastPct.toFixed(1) + '% Con FS' : 'Sin datos'}</span>
      ${deltaHtml}
      ${hasChildren && !showOwnTable ? `<span class="sm-child-count">${node.children.length} dominios ▸</span>` : ''}
      <span class="agg2-chevron" style="margin-left:auto">▼</span>
    </div>
    <div class="agg2-card-body">
      <div class="sm-node-body-inner">
        ${showOwnTable ? `<div class="table-wrap"><table id="${tableId}"></table></div>` : ''}
        ${hasChildren ? `<div class="sm-children" id="${tableId}-children"></div>` : ''}
      </div>
    </div>`;
  container.appendChild(div);
  if (showOwnTable) renderSanMartinTable(tableId, node.monthly, months);
  if (hasChildren) {
    const childContainer = div.querySelector('#' + tableId + '-children');
    node.children.forEach(child => renderSanMartinNode(childContainer, child, depth + 1));
  }
}

function buildSanMartinTab() {
  const container = document.getElementById('sanmartin-tree');
  if (!container || !SAN_MARTIN || !SAN_MARTIN.nodes || !SAN_MARTIN.nodes.length) return;
  container.innerHTML = '';
  const pill = document.getElementById('sm-pill');
  if (pill) {
    const rangeLbl = SAN_MARTIN.range.replace(/^\d+\.\s*/, '');
    pill.textContent = `Rango ${rangeLbl} · ${SAN_MARTIN.months[0]} a ${SAN_MARTIN.months[SAN_MARTIN.months.length - 1]}`;
  }
  SAN_MARTIN.nodes.forEach(node => renderSanMartinNode(container, node, 0));
}

// ─── INIT ────────────────────────────────────────────────────────────────────
renderCategoryTabs();
loadCategory();
buildSanMartinTab();
</script>
</body>
</html>
"""


def main():
    print("Conectando a BigQuery ...")
    client = bigquery.Client(project=BQ_PROJECT)

    print("Buscando última fecha de foto (metadata de partición) ...")
    photo_date = get_latest_photo_date(client)
    print(f"  PHOTO_DATE = {photo_date}")

    print("Consultando BT_LIVE_LISTINGS_MLA para las 10 categorías ...")
    df = query_all_categories(client, photo_date, AGG1_LIST)
    print(f"  {len(df)} filas")

    print("Procesando datos por categoría ...")
    categories, cat_order = build_categories(df)
    for k in cat_order:
        c = categories[k]
        print(f"  {c['label']:32s} agg2={len(c['agg2List'])}  dominios={len(c['DOMAIN_ORDER'])}/{c['totalDomains']}")

    print("Buscando fechas de snapshot mensual (Plan San Martín) ...")
    month_dates = get_monthly_snapshot_dates(client, SAN_MARTIN_MONTHS_BACK)
    print(f"  Meses: {[m for m, _ in month_dates]}")

    print("Consultando histórico del rango 15K-33K para Plan San Martín ...")
    lo, hi = SAN_MARTIN_RANGE_BOUNDS
    history_by_month = {}
    for label, date_str in month_dates:
        print(f"  → {label} ({date_str}) ...")
        history_by_month[label] = query_price_band_snapshot(client, date_str, AGG1_LIST, lo, hi)

    san_martin = build_san_martin(history_by_month, [m for m, _ in month_dates])
    print(f"  {len(san_martin['nodes'])} categorías con datos en el rango 15K-33K")

    print("Generando HTML ...")
    html = HTML_TEMPLATE
    html = html.replace("__PHOTO_DATE__", photo_date)
    html = html.replace("__RANGES_JSON__", json.dumps(RANGE_KEYS, ensure_ascii=False))
    html = html.replace("__CATEGORY_ORDER_JSON__", json.dumps(cat_order, ensure_ascii=False))
    html = html.replace("__CATEGORIES_JSON__", json.dumps(categories, ensure_ascii=False, indent=None))
    html = html.replace("__SAN_MARTIN_JSON__", json.dumps(san_martin, ensure_ascii=False))

    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"OK -> {HTML_PATH}  ({HTML_PATH.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
