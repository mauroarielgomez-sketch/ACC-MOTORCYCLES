"""
generate_qbr_q2.py
──────────────────────────────────────────────────────────────────────────────
Generates acc_motorcycles_qbr_q2.html — standalone QBR Q2 FY'26 HTML for
ACC Motorcycles MLA (Apr + May + Jun 2026).

Data sources:
  - DM_VPA_ROADMAP_FINAL  (PERIOD='QUARTER', FECHA_STRING='Q2 26')
  - BT_ORD_ORDERS         (NMV in ARS, sum Apr+May+Jun 2026 vs 2025)
  - DM_UE_ESTABILIZADA_PROFITABILITY  (VC%, DC%, BM% aggregate Q2)

Usage:
    python generate_qbr_q2.py

Requires:
    pip install google-cloud-bigquery pandas
    gcloud auth application-default login
──────────────────────────────────────────────────────────────────────────────
"""

import sys
import json
import subprocess
import datetime
from pathlib import Path

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    from google.cloud import bigquery
except ImportError:
    print("ERROR: Instalá las dependencias con: pip install google-cloud-bigquery pandas")
    sys.exit(1)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
OUT_PATH      = Path(__file__).parent / "acc_motorcycles_qbr_q2.html"
BQ_PROJECT    = "meli-bi-data"
ROADMAP_TABLE = "`meli-bi-data.WHOWNER.DM_VPA_ROADMAP_FINAL`"
UE_TABLE      = "`meli-bi-data.WHOWNER.DM_UE_ESTABILIZADA_PROFITABILITY`"
AGG1          = "ACC MOTORCYCLES"
SITE          = "MLA"

DASH = "—"

# Q2 vs Plan (hardcoded from planning sheet — quarterly aggregate)
NMV_Q2_VSP = "-19%"

# KPIs to fetch from roadmap (quarterly)
ROADMAP_KPIS = [
    "NSI", "NASP",
    "Visitas", "CVR (Orders / Visits)",
    "Frequency",
    "# Clips",
    "% NMV Clips", "% NMV Affiliates", "# Afiliados",
    "% NMV Buy Box", "CBT Penetration (%NMV)",
    "KMI Scrapping Coverage (%Visits)", "% BPC KMI",
    "% NSI FBM", "Stockouts (As % of FBM GMV)",
    "% Promesas en VIP ≤2D",
    "Benefits Meli Investment %",
    "MAds % NMV",
]


def _q(s):
    """Escape single quotes for BigQuery SQL."""
    return s.replace("'", "\\'")


def _kpi_sql_list(kpis):
    return "'" + "', '".join(_q(k) for k in kpis) + "'"


# ─── BQ QUERIES ───────────────────────────────────────────────────────────────

def query_roadmap_q2(client):
    """Q2 FY'26 quarterly data from DM_VPA_ROADMAP_FINAL."""
    sql = f"""
    SELECT
        TRIM(KPI)     AS KPI,
        VARIATION,
        INICIATIVA,
        VALUE,
        VALUE_STRING,
        COLOR_CODING,
        ORDEN
    FROM {ROADMAP_TABLE}
    WHERE AGG1         = '{AGG1}'
      AND AGG2         = 'ALL'
      AND PERIOD       = 'QUARTER'
      AND FECHA_STRING = 'Q2 26'
      AND SITE         = '{SITE}'
      AND INICIATIVA   IN ('ALL', '3P')
      AND TRIM(KPI)    IN ({_kpi_sql_list(ROADMAP_KPIS)})
    ORDER BY ORDEN, TRIM(KPI), VARIATION, INICIATIVA
    """
    df = client.query(sql).to_dataframe()
    # Prefer INICIATIVA='ALL' over '3P' when both exist for same KPI/VARIATION
    if not df.empty:
        df['_rank'] = df['INICIATIVA'].map({'ALL': 0, '3P': 1}).fillna(2)
        df = (df.sort_values('_rank')
                .drop_duplicates(subset=['KPI', 'VARIATION'], keep='first')
                .drop(columns='_rank')
                .reset_index(drop=True))
    return df


def query_nmv_ars_q2(client):
    """NMV in ARS for Q2 2026 and Q2 2025 from BT_ORD_ORDERS."""
    sql = """
    SELECT
        EXTRACT(YEAR FROM orders.ORD_CLOSED_DT) AS year,
        COALESCE(SUM(CASE
            WHEN (NOT COALESCE(orders.ORD_ORDER_MSHOPS_FLG, FALSE))
                AND (orders.ORD_CATEGORY.MARKETPLACE_ID = 'TM')
                AND orders.ORD_GMV_FLG
                AND (NOT COALESCE(orders.ORD_ORDER_PROXIMITY_FLG, FALSE))
            THEN CASE
                WHEN orders.ORD_CLOSED_DT >= CURRENT_DATE - 45 THEN
                    COALESCE(transactional_forecast.F_TGMVELC,
                             CASE WHEN orders.ORD_TGMV_FLG = true
                                  THEN orders.ORD_ITEM.QTY * orders.ORD_ITEM.UNIT_PRICE END)
                WHEN orders.ORD_TGMV_FLG = true
                    THEN orders.ORD_ITEM.QTY * orders.ORD_ITEM.UNIT_PRICE
            END
            ELSE NULL
        END), 0) AS nmv_ars
    FROM `meli-bi-data.WHOWNER.BT_ORD_ORDERS` AS orders
    LEFT JOIN `meli-bi-data.WHOWNER.BT_ORD_ORDERS_TRANSACTIONAL_FORECAST` AS transactional_forecast
        ON transactional_forecast.ORD_ORDER_ID = orders.ORD_ORDER_ID
    LEFT JOIN `meli-bi-data.WHOWNER.LK_ITE_ITEM_DOMAINS` AS item_domains
        ON item_domains.SIT_SITE_ID = orders.SIT_SITE_ID
        AND item_domains.ITE_ITEM_ID = orders.ORD_ITEM.ID
    WHERE orders.SIT_SITE_ID = 'MLA'
      AND item_domains.DOM_DOMAIN_AGG1 = 'ACC MOTORCYCLES'
      AND (
          (orders.ORD_CLOSED_DT >= DATE('2026-04-01') AND orders.ORD_CLOSED_DT < DATE('2026-07-01'))
          OR
          (orders.ORD_CLOSED_DT >= DATE('2025-04-01') AND orders.ORD_CLOSED_DT < DATE('2025-07-01'))
      )
    GROUP BY 1
    ORDER BY 1
    """
    return client.query(sql).to_dataframe()


def query_vc_dc_bm_q2(client):
    """VC%, DC%, BM% aggregated for Q2 2026 and Q2 2025 from DM_UE_ESTABILIZADA."""
    sql = f"""
    SELECT
        CASE
            WHEN CAST(MONTH_FINAL AS STRING) >= '2026-04'
             AND CAST(MONTH_FINAL AS STRING) <= '2026-06' THEN 2026
            WHEN CAST(MONTH_FINAL AS STRING) >= '2025-04'
             AND CAST(MONTH_FINAL AS STRING) <= '2025-06' THEN 2025
        END AS yr,
        ROUND(SAFE_DIVIDE(SUM(VARIABLE_CONTRIBUTION_TOTAL), SUM(NMV)) * 100, 1) AS VC_PCT,
        ROUND(SAFE_DIVIDE(SUM(DIRECT_CONTRIBUTION_TOTAL),   SUM(NMV)) * 100, 1) AS DC_PCT,
        ROUND(SAFE_DIVIDE(SUM(BUSINESS_MARGIN_TOTAL),       SUM(NMV)) * 100, 1) AS BM_PCT
    FROM {UE_TABLE}
    WHERE SIT_SITE_ID       = 'MLA'
      AND DOM_DOMAIN_AGG1   = 'ACC MOTORCYCLES'
      AND (
          (CAST(MONTH_FINAL AS STRING) >= '2026-04' AND CAST(MONTH_FINAL AS STRING) <= '2026-06')
          OR
          (CAST(MONTH_FINAL AS STRING) >= '2025-04' AND CAST(MONTH_FINAL AS STRING) <= '2025-06')
      )
    GROUP BY 1
    ORDER BY 1
    """
    return client.query(sql).to_dataframe()


# ─── DATA BUILDERS ────────────────────────────────────────────────────────────

def _safe(val):
    """Return displayable string, falling back to DASH."""
    if val is None:
        return DASH
    s = str(val).strip()
    if s in ('', 'None', 'nan', 'NaN', '<NA>'):
        return DASH
    return s


def _get_var(df, kpi, variation):
    """Get VALUE_STRING for one KPI/variation from the quarterly roadmap DataFrame."""
    sub = df[(df['KPI'] == kpi) & (df['VARIATION'] == variation)]
    if sub.empty:
        return DASH
    return _safe(sub.iloc[0]['VALUE_STRING'])


def build_roadmap_dict(df):
    """
    Build flat dict: {short_key: {act, yoy, vsp}} for all roadmap KPIs.
    The short_key is used as the HTML data-key attribute.
    """
    def v(kpi, var):
        return _get_var(df, kpi, var)

    return {
        'nsi':     {'act': v("NSI",     "Actual"), 'yoy': v("NSI",     "YoY"), 'vsp': v("NSI",     "vs Plan")},
        'nasp':    {'act': v("NASP",    "Actual"), 'yoy': v("NASP",    "YoY"), 'vsp': v("NASP",    "vs Plan")},
        'visitas': {'act': v("Visitas", "Actual"), 'yoy': v("Visitas", "YoY"), 'vsp': DASH},
        'cvr':     {
            'act': v("CVR (Orders / Visits)", "Actual"),
            'yoy': v("CVR (Orders / Visits)", "YoY"),
            'vsp': DASH,
        },
        'freq':    {'act': v("Frequency", "Actual"), 'yoy': v("Frequency", "YoY"), 'vsp': DASH},
        'clips_n': {'act': v("# Clips",   "Actual"), 'yoy': v("# Clips",   "YoY"), 'vsp': v("# Clips",   "vs Plan")},
        'clips_p': {
            'act': v("% NMV Clips", "Actual"),
            'yoy': v("% NMV Clips", "YoY"),
            'vsp': v("% NMV Clips", "vs Plan"),
        },
        'afil_n': {
            'act': v("# Afiliados", "Actual"),
            'yoy': v("# Afiliados", "YoY"),
            'vsp': v("# Afiliados", "vs Plan"),
        },
        'afil_p': {
            'act': v("% NMV Affiliates", "Actual"),
            'yoy': v("% NMV Affiliates", "YoY"),
            'vsp': v("% NMV Affiliates", "vs Plan"),
        },
        'buybox': {
            'act': v("% NMV Buy Box", "Actual"),
            'yoy': v("% NMV Buy Box", "YoY"),
            'vsp': v("% NMV Buy Box", "vs Plan"),
        },
        'cbt': {
            'act': v("CBT Penetration (%NMV)", "Actual"),
            'yoy': v("CBT Penetration (%NMV)", "YoY"),
            'vsp': v("CBT Penetration (%NMV)", "vs Plan"),
        },
        'bpckmi': {'act': v("% BPC KMI", "Actual"), 'yoy': DASH, 'vsp': DASH},
        'kmi': {
            'act': v("KMI Scrapping Coverage (%Visits)", "Actual"),
            'yoy': DASH,
            'vsp': DASH,
        },
        'fbm': {
            'act': v("% NSI FBM", "Actual"),
            'yoy': v("% NSI FBM", "YoY"),
            'vsp': v("% NSI FBM", "vs Plan"),
        },
        'stk': {
            'act': v("Stockouts (As % of FBM GMV)", "Actual"),
            'yoy': v("Stockouts (As % of FBM GMV)", "YoY"),
            'vsp': v("Stockouts (As % of FBM GMV)", "vs Plan"),
        },
        'prom': {
            'act': v("% Promesas en VIP ≤2D", "Actual"),
            'yoy': v("% Promesas en VIP ≤2D", "YoY"),
            'vsp': v("% Promesas en VIP ≤2D", "vs Plan"),
        },
        'ben': {
            'act': v("Benefits Meli Investment %", "Actual"),
            'yoy': v("Benefits Meli Investment %", "YoY"),
            'vsp': v("Benefits Meli Investment %", "vs Plan"),
        },
        'mads': {'act': v("MAds % NMV", "Actual"), 'yoy': v("MAds % NMV", "YoY"), 'vsp': DASH},
    }


def build_nmv_dict(df_nmv):
    """Build NMV Q2 dict from BT_ORD_ORDERS data."""
    v2026 = None
    v2025 = None
    for _, row in df_nmv.iterrows():
        yr = int(row['year'])
        val = float(row['nmv_ars']) if row['nmv_ars'] is not None else 0.0
        if yr == 2026:
            v2026 = val
        elif yr == 2025:
            v2025 = val

    if v2026 is None:
        return {'act': DASH, 'yoy': DASH, 'vsp': NMV_Q2_VSP}

    act_str = f"{v2026 / 1e9:.1f}B"
    if v2025 and v2025 != 0:
        yoy_pct = (v2026 / v2025 - 1) * 100
        yoy_str = f"{'+' if yoy_pct >= 0 else ''}{yoy_pct:.0f}%"
    else:
        yoy_str = DASH

    return {'act': act_str, 'yoy': yoy_str, 'vsp': NMV_Q2_VSP}


def build_vc_dc_bm_dict(df_ue):
    """Build VC%, DC%, BM% Q2 dicts from DM_UE_ESTABILIZADA_PROFITABILITY."""
    v2026 = {}
    v2025 = {}
    for _, row in df_ue.iterrows():
        yr = row['yr']
        if yr is None:
            continue
        yr = int(yr)
        vals = {
            'vc': float(row['VC_PCT']) if row['VC_PCT'] is not None else None,
            'dc': float(row['DC_PCT']) if row['DC_PCT'] is not None else None,
            'bm': float(row['BM_PCT']) if row['BM_PCT'] is not None else None,
        }
        if yr == 2026:
            v2026 = vals
        elif yr == 2025:
            v2025 = vals

    def fmt(v):
        return f"{v:.1f} %" if v is not None else DASH

    def fmt_pp(cur, prev):
        if cur is None or prev is None:
            return DASH
        d = round(cur - prev, 2)
        return f"{'+' if d >= 0 else ''}{d:.2f} pp"

    vc26 = v2026.get('vc')
    dc26 = v2026.get('dc')
    bm26 = v2026.get('bm')
    vc25 = v2025.get('vc')
    dc25 = v2025.get('dc')
    bm25 = v2025.get('bm')

    return {
        'vc': {'act': fmt(vc26), 'yoy': fmt_pp(vc26, vc25), 'vsp': DASH},
        'dc': {'act': fmt(dc26), 'yoy': fmt_pp(dc26, dc25), 'vsp': DASH},
        'bm': {'act': fmt(bm26), 'yoy': fmt_pp(bm26, bm25), 'vsp': DASH},
    }


# ─── HTML GENERATION ──────────────────────────────────────────────────────────

def _cls_yoy(val, invert=False):
    """CSS class for YoY cell."""
    v = _safe(val)
    if v in (DASH, 'TBD'):
        return 'mvr-yoy'
    is_pos = not v.lstrip().startswith('-')
    if invert:
        is_pos = not is_pos
    return 'mvr-yoy ' + ('pos' if is_pos else 'neg')


def _cls_vsp(val, invert=False):
    """CSS class for vs Plan cell."""
    v = _safe(val)
    if v in (DASH, 'TBD'):
        return 'mvr-vsp'
    is_pos = not v.lstrip().startswith('-')
    if invert:
        is_pos = not is_pos
    return 'mvr-vsp ' + ('pos' if is_pos else 'neg')


def _td_val(val):
    v = _safe(val)
    if v == 'TBD':
        return f'<td class="mvr-val mvr-tbd">{v}</td>'
    return f'<td class="mvr-val">{v}</td>'


def _td_yoy(val, invert=False):
    v = _safe(val)
    if v == 'TBD':
        return f'<td class="mvr-yoy mvr-tbd">{v}</td>'
    return f'<td class="{_cls_yoy(v, invert)}">{v}</td>'


def _td_vsp(val, invert=False):
    v = _safe(val)
    if v == 'TBD':
        return f'<td class="mvr-vsp mvr-tbd">{v}</td>'
    return f'<td class="{_cls_vsp(v, invert)}">{v}</td>'


def _td_eoy(val):
    v = _safe(val)
    if v == 'TBD':
        return f'<td class="mvr-eoy mvr-tbd">{v}</td>'
    return f'<td class="mvr-eoy">{v}</td>'


def _tr_first(sec, rowspan, kpi, data, key, eoy, inv_yoy=False, inv_vsp=False):
    """Table row with section cell (first row of a section)."""
    kd = data.get(key, {})
    act = kd.get('act', DASH)
    yoy = kd.get('yoy', DASH)
    vsp = kd.get('vsp', DASH)
    return (
        f'  <tr>\n'
        f'    <td class="mvr-sec" rowspan="{rowspan}">{sec}</td>\n'
        f'    <td class="mvr-kpi">{kpi}</td>\n'
        f'    {_td_val(act)}{_td_yoy(yoy, inv_yoy)}{_td_vsp(vsp, inv_vsp)}{_td_eoy(eoy)}\n'
        f'  </tr>'
    )


def _tr_cont(kpi, data, key, eoy, inv_yoy=False, inv_vsp=False):
    """Continuation row (no section cell — part of a rowspan)."""
    kd = data.get(key, {})
    act = kd.get('act', DASH)
    yoy = kd.get('yoy', DASH)
    vsp = kd.get('vsp', DASH)
    return (
        f'  <tr>\n'
        f'    <td class="mvr-kpi">{kpi}</td>\n'
        f'    {_td_val(act)}{_td_yoy(yoy, inv_yoy)}{_td_vsp(vsp, inv_vsp)}{_td_eoy(eoy)}\n'
        f'  </tr>'
    )


def _tr_tbd(kpi):
    """Row with all TBD values (no section cell)."""
    return (
        f'  <tr>\n'
        f'    <td class="mvr-kpi">{kpi}</td>\n'
        f'    <td class="mvr-val mvr-tbd">TBD</td>'
        f'<td class="mvr-yoy mvr-tbd">TBD</td>'
        f'<td class="mvr-vsp mvr-tbd">TBD</td>'
        f'<td class="mvr-eoy mvr-tbd">TBD</td>\n'
        f'  </tr>'
    )


def generate_html(data, ts):
    """Generate the full standalone QBR Q2 HTML string."""

    d = data  # shorthand

    table_rows = '\n'.join([
        # ── Overall Performance (rowspan=6) ────────────────────────────────
        _tr_first("Overall Performance", 6, "NMV (B ARS)",    d, "nmv",  "~235B"),
        _tr_cont("NSI (K unidades)",                          d, "nsi",  "4.7M"),
        _tr_cont("NASP (ARS)",                                d, "nasp", "47.6K"),
        _tr_cont("VC %",                                      d, "vc",   DASH),
        _tr_cont("DC %",                                      d, "dc",   DASH),
        _tr_cont("BM",                                        d, "bm",   DASH),

        # ── Demand & Engagement (rowspan=8) ────────────────────────────────
        _tr_first("Demand &amp; Engagement", 8, "Visitas",    d, "visitas", DASH),
        _tr_cont("CVR (Orders/Visits)",                       d, "cvr",     DASH),
        _tr_cont("Frequency",                                 d, "freq",    "1.3"),
        _tr_cont("# Clips",                                   d, "clips_n", "~64K"),
        _tr_tbd("Share de Clips (%LL con Clips)"),
        _tr_cont("% NMV con Clips",                           d, "clips_p", "19.8%"),
        _tr_cont("# Afiliados",                               d, "afil_n",  "~43K"),
        _tr_cont("% NMV Affiliates",                          d, "afil_p",  "3%"),

        # ── Selection Mgmt (rowspan=1) ─────────────────────────────────────
        _tr_first("Selection Mgmt", 1, "% NMV Buy Box",       d, "buybox", "9.5%"),

        # ── Commercial Excellence (rowspan=2) ──────────────────────────────
        _tr_first("Commercial Excellence", 2, "CBT Penetration (%NMV)", d, "cbt", "2.0%"),
        _tr_tbd("NMV 1P"),

        # ── Price Competitiveness (rowspan=2) ──────────────────────────────
        _tr_first("Price Competitiveness", 2, "% BPC KMI",    d, "bpckmi", DASH),
        _tr_cont("KMI Scrapping Coverage (%Visits)",           d, "kmi",    DASH),

        # ── Shipping & Availability Mgmt (rowspan=3) ───────────────────────
        _tr_first("Shipping &amp; Availability Mgmt", 3,
                  "% NSI FBM",                                 d, "fbm",  "13.2%"),
        # Stockouts: invert YoY and vsp (lower = better)
        _tr_cont("Stockouts (As % of FBM GMV)",               d, "stk",  "37.9%",
                 inv_yoy=True, inv_vsp=True),
        _tr_cont("% Promesas en VIP &le;2D",                  d, "prom", "34.5%"),

        # ── Benefits & Discounts (rowspan=1) ───────────────────────────────
        _tr_first("Benefits &amp; Discounts", 1,
                  "Benefits Meli Investment %",                d, "ben",  "0.64%"),

        # ── Ads (rowspan=1) ────────────────────────────────────────────────
        _tr_first("Ads", 1, "MAds % NMV",                     d, "mads", DASH),
    ])

    qbr_json = json.dumps(data, ensure_ascii=False, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ACC Motorcycles &middot; QBR Q2 FY&#39;26 &middot; MLA</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:      #111318;
    --bg2:     #1a1d24;
    --bg3:     #22262f;
    --border:  #2e3240;
    --text:    #e8eaf0;
    --muted:   #7b8099;
    --yellow:  #FFE600;
    --green:   #22c55e;
    --red:     #ef4444;
    --amber:   #f59e0b;
    --card-bg: #1e2130;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 13px;
    min-height: 100vh;
    padding-bottom: 48px;
  }}

  /* ── HEADER ── */
  .qbr-header {{
    background: linear-gradient(135deg, #0d0f14 0%, #1a1d24 100%);
    border-bottom: 2px solid var(--yellow);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .qbr-header-left {{ display: flex; align-items: center; gap: 16px; }}
  .qbr-badge {{
    background: var(--yellow);
    color: #111;
    font-weight: 800;
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }}
  .qbr-title {{
    font-size: 18px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.3px;
  }}
  .qbr-title span {{ color: var(--yellow); }}
  .qbr-sub {{
    font-size: 11px;
    color: var(--muted);
    margin-top: 3px;
  }}
  .qbr-ts-chip {{
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 5px 14px;
    font-size: 11px;
    color: var(--muted);
    white-space: nowrap;
  }}
  .qbr-ts-chip strong {{ color: var(--text); font-weight: 600; }}

  /* ── MAIN ── */
  .qbr-main {{
    padding: 32px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0;
  }}

  /* ── MVR TABLE ── */
  .mvr-wrap {{
    overflow-x: auto;
    width: 100%;
  }}
  .mvr-table {{
    border-collapse: collapse;
    font-size: 11px;
    width: 100%;
    min-width: 800px;
    max-width: 980px;
    table-layout: fixed;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 4px 24px rgba(0,0,0,.35);
    overflow: hidden;
  }}
  .mvr-table thead tr:first-child th {{
    background: #1a1a2e;
    color: #fff;
    padding: 8px 10px;
    font-weight: 700;
    font-size: 13px;
    text-align: left;
  }}
  .mvr-table thead tr:first-child th.mvr-ph {{
    background: #FFE600;
    color: #111;
    text-align: center;
    font-size: 13px;
  }}
  .mvr-table thead tr:last-child th {{
    background: #FFE600;
    color: #111;
    font-weight: 700;
    font-size: 10px;
    text-align: right;
    padding: 5px 10px;
  }}
  .mvr-sec {{
    background: #404040;
    color: #fff;
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: .5px;
    text-align: center;
    vertical-align: middle;
    padding: 4px;
    border-bottom: 1px solid rgba(255,255,255,.08);
    width: 80px;
  }}
  .mvr-kpi {{
    color: #1a1a1a;
    font-size: 11px;
    text-align: left;
    padding: 5px 10px;
    border-bottom: 1px solid #f0f2f5;
    width: 210px;
  }}
  .mvr-val, .mvr-eoy {{
    color: #333;
    text-align: right;
    padding: 5px 10px;
    font-weight: 600;
    border-bottom: 1px solid #f0f2f5;
    width: 134px;
  }}
  .mvr-yoy, .mvr-vsp {{
    text-align: right;
    padding: 5px 10px;
    font-weight: 600;
    border-bottom: 1px solid #f0f2f5;
    width: 134px;
    color: #bbb;
  }}
  .mvr-yoy.pos, .mvr-vsp.pos {{ color: #1b8a3f; }}
  .mvr-yoy.neg, .mvr-vsp.neg {{ color: #c0392b; }}
  .mvr-tbd {{ color: #f59e0b !important; font-style: italic; }}

  /* ── LEGEND BAR ── */
  .qbr-legend {{
    display: flex;
    gap: 20px;
    align-items: center;
    margin-bottom: 14px;
    font-size: 10px;
    color: var(--muted);
    flex-wrap: wrap;
  }}
  .qbr-legend-item {{ display: flex; align-items: center; gap: 5px; }}
  .qbr-dot {{
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  }}
  .qbr-dot.green {{ background: #1b8a3f; }}
  .qbr-dot.red   {{ background: #c0392b; }}
  .qbr-dot.amber {{ background: #f59e0b; }}
  .qbr-dot.gray  {{ background: #bbb; }}

  /* ── FOOTER ── */
  .qbr-footer {{
    margin-top: 20px;
    font-size: 10px;
    color: var(--muted);
    line-height: 1.7;
  }}
  .qbr-footer a {{ color: var(--muted); text-decoration: none; }}

  /* ── PRINT ── */
  @media print {{
    body {{ background: #fff; color: #000; }}
    .qbr-header {{ background: #fff; border-bottom: 2px solid #FFE600; }}
    .qbr-main {{ padding: 16px; }}
  }}
</style>
</head>
<body>

<div class="qbr-header">
  <div class="qbr-header-left">
    <div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span class="qbr-badge">QBR</span>
        <div class="qbr-title">MLA &middot; ACC Motorcycles &middot; <span>QBR Q2 FY&#39;26</span></div>
      </div>
      <div class="qbr-sub">Q2 FY&#39;26 (Abr &middot; May &middot; Jun) &mdash; Actual / YoY / vs Plan</div>
    </div>
  </div>
  <div class="qbr-ts-chip">
    Datos al <strong id="qbr-ts">{ts}</strong>
  </div>
</div>

<div class="qbr-main">

  <div class="qbr-legend">
    <div class="qbr-legend-item"><div class="qbr-dot green"></div> Positivo</div>
    <div class="qbr-legend-item"><div class="qbr-dot red"></div> Negativo</div>
    <div class="qbr-legend-item"><div class="qbr-dot amber"></div> TBD / sin datos</div>
    <div class="qbr-legend-item"><div class="qbr-dot gray"></div> Sin variaci&oacute;n / N/A</div>
    <div class="qbr-legend-item" style="margin-left:12px;color:#aaa;">
      * Stockouts: rojo = sube (negativo), verde = baja (positivo)
    </div>
  </div>

  <div class="mvr-wrap">
    <table class="mvr-table">
      <thead>
        <tr>
          <th rowspan="2" style="width:80px;">Secci&oacute;n</th>
          <th rowspan="2" style="width:210px;">KPI</th>
          <th class="mvr-ph" colspan="3">Q2 FY&#39;26</th>
          <th class="mvr-ph" style="width:100px;text-align:center;">EOY</th>
        </tr>
        <tr>
          <th style="width:110px;text-align:right;">Actual</th>
          <th style="width:110px;text-align:right;">YoY</th>
          <th style="width:110px;text-align:right;">vs Plan</th>
          <th style="width:100px;text-align:right;">Target FY&#39;26</th>
        </tr>
      </thead>
      <tbody>
{table_rows}
      </tbody>
    </table>
  </div>

  <div class="qbr-footer">
    <p>Fuentes: DM_VPA_ROADMAP_FINAL (PERIOD=QUARTER, FECHA_STRING=&#39;Q2 26&#39;) &middot;
       BT_ORD_ORDERS (NMV ARS) &middot;
       DM_UE_ESTABILIZADA_PROFITABILITY (VC/DC/BM)</p>
    <p>NMV vs Plan = {NMV_Q2_VSP} (planning sheet, fijo). Generado: {ts}</p>
  </div>

</div>

<script>
// QBR Q2 FY'26 embedded data — generated by generate_qbr_q2.py
window.QBR_DATA = {qbr_json};
window.QBR_TS   = {json.dumps(ts)};
</script>

<script>
// Ensure timestamp is shown; values are already baked into HTML
document.addEventListener('DOMContentLoaded', function() {{
  var tsEl = document.getElementById('qbr-ts');
  if (tsEl && window.QBR_TS) {{
    tsEl.textContent = window.QBR_TS;
  }}
}});
</script>

</body>
</html>"""

    return html


# ─── GIT PUSH ─────────────────────────────────────────────────────────────────

def _push_to_github(ts_str):
    """Commit and push the generated HTML to GitHub Pages."""
    repo_dir = OUT_PATH.parent
    commit_msg = f"Add QBR Q2 FY26 standalone HTML: {ts_str}"

    commands = [
        ["git", "-C", str(repo_dir), "add", OUT_PATH.name, Path(__file__).name],
        ["git", "-C", str(repo_dir), "commit", "-m", commit_msg],
        ["git", "-C", str(repo_dir), "push", "origin", "main"],
    ]

    print("  Subiendo a GitHub ...")
    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if "nothing to commit" in (result.stdout + result.stderr):
                print("  Sin cambios nuevos para commitear.")
                return
            print(f"  Error en git: {result.stderr.strip()}")
            return
    print("  Push a GitHub Pages exitoso.")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"[{ts}] Iniciando generacion de {OUT_PATH.name} ...")

    # 1. Connect to BigQuery
    print("  Conectando a BigQuery ...")
    try:
        client = bigquery.Client(project=BQ_PROJECT)
    except Exception as e:
        print(f"ERROR al conectar con BigQuery: {e}")
        sys.exit(1)

    # 2. Query roadmap Q2 (most KPIs)
    print("  Consultando DM_VPA_ROADMAP_FINAL (QUARTER, Q2 26) ...")
    try:
        df_rdm = query_roadmap_q2(client)
        print(f"    {len(df_rdm)} filas retornadas del roadmap Q2.")
    except Exception as e:
        print(f"  Error en roadmap Q2: {e}")
        df_rdm = None

    # 3. Query NMV in ARS (BT_ORD_ORDERS, Apr+May+Jun)
    print("  Consultando NMV ARS Q2 (BT_ORD_ORDERS) ...")
    try:
        df_nmv = query_nmv_ars_q2(client)
        print(f"    {len(df_nmv)} filas retornadas de NMV ARS.")
    except Exception as e:
        print(f"  Error en NMV ARS Q2: {e}")
        df_nmv = None

    # 4. Query VC/DC/BM Q2 (DM_UE_ESTABILIZADA_PROFITABILITY)
    print("  Consultando VC/DC/BM Q2 (DM_UE_ESTABILIZADA_PROFITABILITY) ...")
    try:
        df_ue = query_vc_dc_bm_q2(client)
        print(f"    {len(df_ue)} filas retornadas de UE.")
    except Exception as e:
        print(f"  Error en VC/DC/BM Q2: {e}")
        df_ue = None

    # 5. Build data dict
    print("  Construyendo diccionario de datos ...")

    if df_rdm is not None and not df_rdm.empty:
        rdm_data = build_roadmap_dict(df_rdm)
    else:
        print("  ADVERTENCIA: Sin datos del roadmap Q2 — usando placeholders.")
        rdm_data = {}

    nmv_data = build_nmv_dict(df_nmv) if df_nmv is not None and not df_nmv.empty else \
               {'act': DASH, 'yoy': DASH, 'vsp': NMV_Q2_VSP}

    if df_ue is not None and not df_ue.empty:
        ue_data = build_vc_dc_bm_dict(df_ue)
    else:
        ue_data = {
            'vc': {'act': DASH, 'yoy': DASH, 'vsp': DASH},
            'dc': {'act': DASH, 'yoy': DASH, 'vsp': DASH},
            'bm': {'act': DASH, 'yoy': DASH, 'vsp': DASH},
        }

    # Merge all data into a single flat dict
    data = {'nmv': nmv_data}
    data.update(rdm_data)
    data.update(ue_data)   # vc, dc, bm override roadmap if present

    # Print summary
    print("  Resumen de valores:")
    for k, v in data.items():
        print(f"    {k}: act={v.get('act','?')} | yoy={v.get('yoy','?')} | vsp={v.get('vsp','?')}")

    # 6. Generate HTML
    print(f"  Generando HTML standalone ...")
    html = generate_html(data, ts)

    # 7. Write to file
    OUT_PATH.write_text(html, encoding='utf-8')
    print(f"  HTML escrito: {OUT_PATH}  ({len(html):,} bytes)")

    # 8. Git commit + push
    _push_to_github(ts)

    print(f"\n[OK] {OUT_PATH.name} generado exitosamente.")
    print(f"     Timestamp: {ts}")


if __name__ == "__main__":
    main()
