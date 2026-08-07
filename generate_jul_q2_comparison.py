"""
generate_jul_q2_comparison.py
──────────────────────────────────────────────────────────────────────────────
Generates acc_motorcycles_jul_q2_comparison.html — standalone comparison HTML
for ACC Motorcycles MLA showing Jul'26 vs Q2 FY'26 side by side.

Columns: Sección | KPI | Jul'26 (Actual / YoY / vs Plan) | Q2 FY'26 (Actual / YoY / vs Plan) | EOY Target FY'26

Data sources:
  - DM_VPA_ROADMAP_FINAL  PERIOD='MONTH',   FECHA_STRING='Jul 26'
  - DM_VPA_ROADMAP_FINAL  PERIOD='QUARTER', FECHA_STRING='Q2 26'
  - BT_ORD_ORDERS         NMV in ARS (Jul 2026 vs Jul 2025 / Q2 2026 vs Q2 2025)
  - DM_UE_ESTABILIZADA_PROFITABILITY  VC%, DC%, BM%
  - Hardcoded: NMV vs Plan Jul = '-26.1%'  |  Q2 = '-19%'

Usage:
    python generate_jul_q2_comparison.py

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

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    from google.cloud import bigquery
except ImportError:
    print("ERROR: pip install google-cloud-bigquery pandas")
    sys.exit(1)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
OUT_PATH      = Path(__file__).parent / "acc_motorcycles_jul_q2_comparison.html"
BQ_PROJECT    = "meli-bi-data"
ROADMAP_TABLE = "`meli-bi-data.WHOWNER.DM_VPA_ROADMAP_FINAL`"
UE_TABLE      = "`meli-bi-data.WHOWNER.DM_UE_ESTABILIZADA_PROFITABILITY`"
AGG1          = "ACC MOTORCYCLES"
SITE          = "MLA"
DASH          = "—"

NMV_JUL_VSP = "-26.1%"
NMV_Q2_VSP  = "-19%"

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
    return s.replace("'", "\\'")


def _kpi_sql(kpis):
    return "'" + "', '".join(_q(k) for k in kpis) + "'"


# ─── BQ QUERIES ───────────────────────────────────────────────────────────────

def query_roadmap(client, period, fecha_string):
    """Query roadmap for a specific PERIOD/FECHA_STRING combo."""
    sql = f"""
    SELECT
        TRIM(KPI) AS KPI,
        VARIATION, INICIATIVA,
        VALUE, VALUE_STRING, COLOR_CODING, ORDEN
    FROM {ROADMAP_TABLE}
    WHERE AGG1         = '{AGG1}'
      AND AGG2         = 'ALL'
      AND PERIOD       = '{period}'
      AND FECHA_STRING = '{fecha_string}'
      AND SITE         = '{SITE}'
      AND INICIATIVA   IN ('ALL', '3P')
      AND TRIM(KPI)    IN ({_kpi_sql(ROADMAP_KPIS)})
    ORDER BY ORDEN, TRIM(KPI), VARIATION, INICIATIVA
    """
    df = client.query(sql).to_dataframe()
    if not df.empty:
        df['_rank'] = df['INICIATIVA'].map({'ALL': 0, '3P': 1}).fillna(2)
        df = (df.sort_values('_rank')
                .drop_duplicates(subset=['KPI', 'VARIATION'], keep='first')
                .drop(columns='_rank')
                .reset_index(drop=True))
    return df


def _nmv_sql(start26, end26, start25, end25):
    return f"""
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
          (orders.ORD_CLOSED_DT >= DATE('{start26}') AND orders.ORD_CLOSED_DT < DATE('{end26}'))
          OR
          (orders.ORD_CLOSED_DT >= DATE('{start25}') AND orders.ORD_CLOSED_DT < DATE('{end25}'))
      )
    GROUP BY 1
    ORDER BY 1
    """


def query_nmv_jul(client):
    return client.query(_nmv_sql('2026-07-01', '2026-08-01', '2025-07-01', '2025-08-01')).to_dataframe()


def query_nmv_q2(client):
    return client.query(_nmv_sql('2026-04-01', '2026-07-01', '2025-04-01', '2025-07-01')).to_dataframe()


def _ue_sql(yr_expr, where_cond):
    return f"""
    SELECT
        {yr_expr} AS yr,
        ROUND(SAFE_DIVIDE(SUM(VARIABLE_CONTRIBUTION_TOTAL), SUM(NMV)) * 100, 1) AS VC_PCT,
        ROUND(SAFE_DIVIDE(SUM(DIRECT_CONTRIBUTION_TOTAL),   SUM(NMV)) * 100, 1) AS DC_PCT,
        ROUND(SAFE_DIVIDE(SUM(BUSINESS_MARGIN_TOTAL),       SUM(NMV)) * 100, 1) AS BM_PCT
    FROM {UE_TABLE}
    WHERE SIT_SITE_ID     = 'MLA'
      AND DOM_DOMAIN_AGG1 = 'ACC MOTORCYCLES'
      AND ({where_cond})
    GROUP BY 1
    ORDER BY 1
    """


def query_ue_jul(client):
    expr = ("CASE "
            "WHEN CAST(MONTH_FINAL AS STRING) = '2026-07' THEN 2026 "
            "WHEN CAST(MONTH_FINAL AS STRING) = '2025-07' THEN 2025 "
            "END")
    cond = ("CAST(MONTH_FINAL AS STRING) = '2026-07' "
            "OR CAST(MONTH_FINAL AS STRING) = '2025-07'")
    return client.query(_ue_sql(expr, cond)).to_dataframe()


def query_ue_q2(client):
    expr = ("CASE "
            "WHEN CAST(MONTH_FINAL AS STRING) >= '2026-04' "
            " AND CAST(MONTH_FINAL AS STRING) <= '2026-06' THEN 2026 "
            "WHEN CAST(MONTH_FINAL AS STRING) >= '2025-04' "
            " AND CAST(MONTH_FINAL AS STRING) <= '2025-06' THEN 2025 "
            "END")
    cond = ("(CAST(MONTH_FINAL AS STRING) >= '2026-04' AND CAST(MONTH_FINAL AS STRING) <= '2026-06') "
            "OR (CAST(MONTH_FINAL AS STRING) >= '2025-04' AND CAST(MONTH_FINAL AS STRING) <= '2025-06')")
    return client.query(_ue_sql(expr, cond)).to_dataframe()


# ─── DATA BUILDERS ────────────────────────────────────────────────────────────

def _safe(val):
    if val is None:
        return DASH
    s = str(val).strip()
    return DASH if s in ('', 'None', 'nan', 'NaN', '<NA>') else s


def _get(df, kpi, variation):
    if df is None or df.empty:
        return DASH
    sub = df[(df['KPI'] == kpi) & (df['VARIATION'] == variation)]
    return DASH if sub.empty else _safe(sub.iloc[0]['VALUE_STRING'])


def build_rdm(df, is_jul=False):
    """Build flat {key: {act, yoy, vsp}} from a roadmap DataFrame.
    is_jul=True injects estimated vs Plan for Jul (same as main HTML VSP_EST).
    For Q2 those KPIs have no plan → DASH.
    """
    v = lambda kpi, var: _get(df, kpi, var)
    J = is_jul  # shorthand
    return {
        'nsi':     {'act': v("NSI",                              "Actual"), 'yoy': v("NSI",                              "YoY"), 'vsp': v("NSI",                              "vs Plan")},
        'nasp':    {'act': v("NASP",                             "Actual"), 'yoy': v("NASP",                             "YoY"), 'vsp': v("NASP",                             "vs Plan")},
        'visitas': {'act': v("Visitas",                          "Actual"), 'yoy': v("Visitas",                          "YoY"), 'vsp': DASH},
        'cvr':     {'act': v("CVR (Orders / Visits)",            "Actual"), 'yoy': v("CVR (Orders / Visits)",            "YoY"), 'vsp': DASH},
        'freq':    {'act': v("Frequency",                        "Actual"), 'yoy': v("Frequency",                        "YoY"), 'vsp': '-2%'    if J else DASH},
        'clips_n': {'act': v("# Clips",                          "Actual"), 'yoy': v("# Clips",                          "YoY"), 'vsp': '+7%'    if J else DASH},
        'clips_p': {'act': v("% NMV Clips",                      "Actual"), 'yoy': v("% NMV Clips",                      "YoY"), 'vsp': '+6.2 pp' if J else DASH},
        'afil_n':  {'act': v("# Afiliados",                      "Actual"), 'yoy': v("# Afiliados",                      "YoY"), 'vsp': '+17%'   if J else DASH},
        'afil_p':  {'act': v("% NMV Affiliates",                 "Actual"), 'yoy': v("% NMV Affiliates",                 "YoY"), 'vsp': '-2.1 pp' if J else DASH},
        'buybox':  {'act': v("% NMV Buy Box",                    "Actual"), 'yoy': v("% NMV Buy Box",                    "YoY"), 'vsp': '+2.0 pp' if J else DASH},
        'cbt':     {'act': v("CBT Penetration (%NMV)",           "Actual"), 'yoy': v("CBT Penetration (%NMV)",           "YoY"), 'vsp': '+0.2 pp' if J else DASH},
        'bpckmi':  {'act': v("% BPC KMI",                        "Actual"), 'yoy': DASH,                                         'vsp': DASH},
        'kmi':     {'act': v("KMI Scrapping Coverage (%Visits)", "Actual"), 'yoy': DASH,                                         'vsp': DASH},
        'fbm':     {'act': v("% NSI FBM",                        "Actual"), 'yoy': v("% NSI FBM",                        "YoY"), 'vsp': '+6.8 pp'  if J else DASH},
        'stk':     {'act': v("Stockouts (As % of FBM GMV)",      "Actual"), 'yoy': v("Stockouts (As % of FBM GMV)",      "YoY"), 'vsp': '-17.8 pp' if J else DASH},
        'prom':    {'act': v("% Promesas en VIP ≤2D",        "Actual"), 'yoy': v("% Promesas en VIP ≤2D",        "YoY"), 'vsp': '+5.0 pp'  if J else DASH},
        'ben':     {'act': v("Benefits Meli Investment %",       "Actual"), 'yoy': v("Benefits Meli Investment %",       "YoY"), 'vsp': '+0.16 pp' if J else DASH},
        'mads':    {'act': v("MAds % NMV",                       "Actual"), 'yoy': v("MAds % NMV",                       "YoY"), 'vsp': DASH},
        'kb1':     {'act': DASH,                                             'yoy': DASH,                                         'vsp': DASH},
    }


def build_nmv(df_nmv, vsp_hardcoded):
    """Build NMV {act, yoy, vsp} from BT_ORD_ORDERS result."""
    v2026 = v2025 = None
    if df_nmv is not None:
        for _, row in df_nmv.iterrows():
            yr = int(row['year'])
            val = float(row['nmv_ars']) if row['nmv_ars'] is not None else 0.0
            if yr == 2026:
                v2026 = val
            elif yr == 2025:
                v2025 = val
    if v2026 is None:
        return {'act': DASH, 'yoy': DASH, 'vsp': vsp_hardcoded}
    act_str = f"{v2026 / 1e9:.1f}B"
    if v2025 and v2025 != 0:
        pct = (v2026 / v2025 - 1) * 100
        yoy_str = f"{'+' if pct >= 0 else ''}{pct:.0f}%"
    else:
        yoy_str = DASH
    return {'act': act_str, 'yoy': yoy_str, 'vsp': vsp_hardcoded}


def build_ue(df_ue):
    """Build {vc, dc, bm} dicts from DM_UE_ESTABILIZADA_PROFITABILITY result."""
    v26 = {}
    v25 = {}
    if df_ue is not None:
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
                v26 = vals
            elif yr == 2025:
                v25 = vals

    def fmt(v):
        return f"{v:.1f} %" if v is not None else DASH

    def pp(a, b):
        if a is None or b is None:
            return DASH
        d = round(a - b, 2)
        return f"{'+' if d >= 0 else ''}{d:.2f} pp"

    return {
        'vc': {'act': fmt(v26.get('vc')), 'yoy': pp(v26.get('vc'), v25.get('vc')), 'vsp': DASH},
        'dc': {'act': fmt(v26.get('dc')), 'yoy': pp(v26.get('dc'), v25.get('dc')), 'vsp': DASH},
        'bm': {'act': fmt(v26.get('bm')), 'yoy': pp(v26.get('bm'), v25.get('bm')), 'vsp': DASH},
    }


def merge_period(rdm, nmv_d, ue_d):
    """Combine roadmap + NMV + UE into one flat dict for a single period."""
    d = {'nmv': nmv_d}
    d.update(rdm)
    d.update(ue_d)   # vc, dc, bm override roadmap entries
    return d


# ─── HTML CELL HELPERS ────────────────────────────────────────────────────────

def _color_cls(base, val, invert=False):
    v = _safe(val)
    if v in (DASH, 'TBD', ''):
        return base
    is_pos = not v.lstrip().startswith('-')
    if invert:
        is_pos = not is_pos
    return base + (' pos' if is_pos else ' neg')


def _td(cls, val):
    v = _safe(val)
    extra = ' mvr-tbd' if v == 'TBD' else ''
    return f'<td class="{cls}{extra}">{v}</td>'


def _period_cells(pd, key, inv_yoy=False, inv_vsp=False, sep=False):
    """Return the 3 TD cells (Actual, YoY, vs Plan) for one period."""
    kd  = pd.get(key, {})
    act = kd.get('act', DASH)
    yoy = kd.get('yoy', DASH)
    vsp = kd.get('vsp', DASH)
    act_cls = 'mvr-val' + (' col-sep' if sep else '')
    return (
        _td(act_cls, act) +
        _td(_color_cls('mvr-yoy', yoy, inv_yoy), yoy) +
        _td(_color_cls('mvr-vsp', vsp, inv_vsp), vsp)
    )


def _td_eoy(val):
    v = _safe(val)
    extra = ' mvr-tbd' if v == 'TBD' else ''
    return f'<td class="mvr-eoy{extra}">{v}</td>'


def _tr_first(sec, rowspan, kpi, jd, qd, key, eoy, inv_yoy=False, inv_vsp=False):
    return (
        f'  <tr>\n'
        f'    <td class="mvr-sec" rowspan="{rowspan}">{sec}</td>\n'
        f'    <td class="mvr-kpi">{kpi}</td>\n'
        f'    {_period_cells(jd, key, inv_yoy, inv_vsp)}'
        f'{_period_cells(qd, key, inv_yoy, inv_vsp, sep=True)}'
        f'{_td_eoy(eoy)}\n'
        f'  </tr>'
    )


def _tr_cont(kpi, jd, qd, key, eoy, inv_yoy=False, inv_vsp=False):
    return (
        f'  <tr>\n'
        f'    <td class="mvr-kpi">{kpi}</td>\n'
        f'    {_period_cells(jd, key, inv_yoy, inv_vsp)}'
        f'{_period_cells(qd, key, inv_yoy, inv_vsp, sep=True)}'
        f'{_td_eoy(eoy)}\n'
        f'  </tr>'
    )


def _tr_tbd(kpi):
    cell = '<td class="mvr-val mvr-tbd">TBD</td><td class="mvr-yoy mvr-tbd">TBD</td><td class="mvr-vsp mvr-tbd">TBD</td>'
    cell_sep = '<td class="mvr-val col-sep mvr-tbd">TBD</td><td class="mvr-yoy mvr-tbd">TBD</td><td class="mvr-vsp mvr-tbd">TBD</td>'
    return (
        f'  <tr>\n'
        f'    <td class="mvr-kpi">{kpi}</td>\n'
        f'    {cell}{cell_sep}<td class="mvr-eoy mvr-tbd">TBD</td>\n'
        f'  </tr>'
    )


# ─── HTML GENERATION ──────────────────────────────────────────────────────────

def generate_html(jul_d, q2_d, ts):
    """Generate the full standalone comparison HTML."""

    jd = jul_d
    qd = q2_d

    table_rows = '\n'.join([
        # ── Overall Performance (6 rows) ─────────────────────────────────────
        _tr_first("Overall<br>Performance", 6,
                  "NMV (B ARS)",                         jd, qd, "nmv",    "~235B"),
        _tr_cont( "NSI (K unidades)",                    jd, qd, "nsi",    "4.7M"),
        _tr_cont( "NASP (ARS)",                          jd, qd, "nasp",   "47.6K"),
        _tr_cont( "VC %",                                jd, qd, "vc",     DASH),
        _tr_cont( "DC %",                                jd, qd, "dc",     DASH),
        _tr_cont( "BM",                                  jd, qd, "bm",     DASH),

        # ── Demand & Engagement (8 rows) ─────────────────────────────────────
        _tr_first("Demand &amp;<br>Engagement", 8,
                  "Visitas",                             jd, qd, "visitas", DASH),
        _tr_cont( "CVR (Orders/Visits)",                 jd, qd, "cvr",    DASH),
        _tr_cont( "Frequency",                           jd, qd, "freq",   "1.3"),
        _tr_cont( "# Clips",                             jd, qd, "clips_n","~64K"),
        _tr_tbd(  "Share de Clips (%LL con Clips)"),
        _tr_cont( "% NMV con Clips",                     jd, qd, "clips_p","19.8%"),
        _tr_cont( "# Afiliados",                         jd, qd, "afil_n", "~43K"),
        _tr_cont( "% NMV Affiliates",                    jd, qd, "afil_p", "3%"),

        # ── Selection Mgmt (1 row) ───────────────────────────────────────────
        _tr_first("Selection<br>Mgmt", 1,
                  "% NMV Buy Box",                       jd, qd, "buybox", "9.5%"),

        # ── Commercial Excellence (2 rows) ───────────────────────────────────
        _tr_first("Commercial<br>Excellence", 2,
                  "CBT Penetration (%NMV)",              jd, qd, "cbt",    "2.0%"),
        _tr_tbd(  "NMV 1P"),

        # ── Price Competitiveness (2 rows) ───────────────────────────────────
        _tr_first("Price<br>Competitiveness", 2,
                  "% BPC KMI",                           jd, qd, "bpckmi", DASH),
        _tr_cont( "KMI Scrapping Coverage (%Visits)",    jd, qd, "kmi",    DASH),

        # ── Shipping & Availability Mgmt (3 rows) ────────────────────────────
        _tr_first("Shipping &amp;<br>Availability Mgmt", 3,
                  "% NSI FBM",                           jd, qd, "fbm",   "13.2%"),
        _tr_cont( "Stockouts (As % of FBM GMV)",         jd, qd, "stk",   "37.9%",
                  inv_yoy=True, inv_vsp=True),
        _tr_cont( "% Promesas en VIP &le;2D",            jd, qd, "prom",  "34.5%"),

        # ── Benefits & Discounts (1 row) ─────────────────────────────────────
        _tr_first("Benefits &amp;<br>Discounts", 1,
                  "Benefits Meli Investment %",          jd, qd, "ben",   "0.64%"),

        # ── Ads (1 row) ───────────────────────────────────────────────────────
        _tr_first("Ads", 1,
                  "MAds % NMV",                          jd, qd, "mads",  "1.9%"),

        # ── KB #1 (1 row) ─────────────────────────────────────────────────────
        _tr_first("KB #1", 1,
                  "% NMV Sellers 80/20 &ge; Cluster In Mature &amp; UP",
                  jd, qd, "kb1", "TBD"),
    ])

    all_data_json = json.dumps({'jul': jul_d, 'q2': q2_d}, ensure_ascii=False, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ACC Motorcycles &middot; Jul&#39;26 vs Q2 FY&#39;26 &middot; MLA</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg:     #111318;
    --bg2:    #1a1d24;
    --bg3:    #22262f;
    --border: #2e3240;
    --text:   #e8eaf0;
    --muted:  #7b8099;
    --yellow: #FFE600;
    --green:  #1b8a3f;
    --red:    #c0392b;
    --amber:  #f59e0b;
    --purple: #7c3aed;
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
  .hdr {{
    background: linear-gradient(135deg, #0d0f14 0%, #1a1d24 100%);
    border-bottom: 2px solid var(--yellow);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .hdr-left  {{ display: flex; align-items: center; gap: 16px; }}
  .hdr-right {{ display: flex; align-items: center; gap: 12px; }}
  .badge {{
    background: var(--yellow);
    color: #111;
    font-weight: 800;
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }}
  .hdr-title {{
    font-size: 18px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.3px;
  }}
  .hdr-title span {{ color: var(--yellow); }}
  .hdr-sub {{ font-size: 11px; color: var(--muted); margin-top: 3px; }}
  .ts-chip {{
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 5px 14px;
    font-size: 11px;
    color: var(--muted);
    white-space: nowrap;
  }}
  .ts-chip strong {{ color: var(--text); font-weight: 600; }}
  .btn-export {{
    background: var(--purple);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    letter-spacing: 0.3px;
    transition: background .15s;
  }}
  .btn-export:hover {{ background: #6d28d9; }}

  /* ── MAIN ── */
  .main {{
    padding: 28px 32px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0;
  }}

  /* ── LEGEND ── */
  .legend {{
    display: flex;
    gap: 20px;
    align-items: center;
    margin-bottom: 14px;
    font-size: 10px;
    color: var(--muted);
    flex-wrap: wrap;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .dot.green {{ background: #1b8a3f; }}
  .dot.red   {{ background: #c0392b; }}
  .dot.amber {{ background: #f59e0b; }}
  .dot.gray  {{ background: #bbb; }}

  /* ── TABLE ── */
  .mvr-wrap {{ overflow-x: auto; width: 100%; }}
  .mvr-table {{
    border-collapse: collapse;
    font-size: 11px;
    min-width: 920px;
    table-layout: fixed;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 4px 24px rgba(0,0,0,.35);
    overflow: hidden;
  }}

  /* Group header row */
  .mvr-table thead tr:first-child th {{
    background: #1a1a2e;
    color: #fff;
    padding: 8px 10px;
    font-weight: 700;
    font-size: 12px;
    text-align: left;
  }}
  .mvr-table thead tr:first-child th.mvr-ph {{
    background: var(--yellow);
    color: #111;
    text-align: center;
    font-size: 12px;
    font-weight: 800;
  }}
  .mvr-table thead tr:first-child th.sep-hdr {{
    border-left: 3px solid #1a1a2e;
  }}
  .mvr-table thead tr:first-child th.eoy-hdr {{
    background: var(--yellow);
    color: #111;
    text-align: center;
    font-size: 11px;
    font-weight: 700;
    border-left: 3px solid #1a1a2e;
  }}

  /* Sub-header row */
  .mvr-table thead tr:last-child th {{
    background: var(--yellow);
    color: #111;
    font-weight: 700;
    font-size: 10px;
    text-align: right;
    padding: 5px 8px;
  }}
  .mvr-table thead tr:last-child th.sep-sub {{
    border-left: 3px solid #1a1a2e;
  }}

  /* Body cells */
  .mvr-sec {{
    background: #404040;
    color: #fff;
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: .5px;
    text-align: center;
    vertical-align: middle;
    padding: 4px 3px;
    border-bottom: 1px solid rgba(255,255,255,.08);
    line-height: 1.4;
    width: 72px;
  }}
  .mvr-kpi {{
    color: #1a1a1a;
    font-size: 11px;
    text-align: left;
    padding: 5px 8px;
    border-bottom: 1px solid #f0f2f5;
    width: 190px;
  }}
  .mvr-val {{
    color: #333;
    text-align: right;
    padding: 5px 8px;
    font-weight: 600;
    border-bottom: 1px solid #f0f2f5;
    width: 85px;
  }}
  .mvr-yoy, .mvr-vsp {{
    text-align: right;
    padding: 5px 8px;
    font-weight: 600;
    border-bottom: 1px solid #f0f2f5;
    color: #bbb;
    width: 78px;
  }}
  .mvr-eoy {{
    color: #333;
    text-align: center;
    padding: 5px 8px;
    font-weight: 600;
    border-bottom: 1px solid #f0f2f5;
    border-left: 3px solid #1a1a2e;
    width: 88px;
  }}
  .mvr-yoy.pos, .mvr-vsp.pos {{ color: #1b8a3f; }}
  .mvr-yoy.neg, .mvr-vsp.neg {{ color: #c0392b; }}
  .mvr-tbd {{ color: #f59e0b !important; font-style: italic; }}

  /* Separator before Q2 columns */
  .col-sep {{ border-left: 3px solid #c8c8c8 !important; }}

  /* ── FOOTER ── */
  .footer {{
    margin-top: 20px;
    font-size: 10px;
    color: var(--muted);
    line-height: 1.8;
  }}

  /* ── PRINT ── */
  @media print {{
    body {{ background: #fff; color: #000; }}
    .hdr {{ background: #fff; border-bottom: 2px solid var(--yellow); }}
    .main {{ padding: 16px; }}
    .btn-export {{ display: none; }}
  }}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-left">
    <div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span class="badge">MVR</span>
        <div class="hdr-title">MLA &middot; ACC Motorcycles &middot; <span>Jul&#39;26 vs Q2 FY&#39;26</span></div>
      </div>
      <div class="hdr-sub">Jul&#39;26 &amp; Q2 FY&#39;26 (Abr &middot; May &middot; Jun) &mdash; Actual / YoY / vs Plan</div>
    </div>
  </div>
  <div class="hdr-right">
    <div class="ts-chip">Datos al <strong id="comp-ts">{ts}</strong></div>
    <button class="btn-export" onclick="window.print()">Exportar / Imprimir</button>
  </div>
</div>

<div class="main">

  <div class="legend">
    <div class="legend-item"><div class="dot green"></div> Positivo</div>
    <div class="legend-item"><div class="dot red"></div> Negativo</div>
    <div class="legend-item"><div class="dot amber"></div> TBD / sin datos</div>
    <div class="legend-item"><div class="dot gray"></div> N/A</div>
    <div class="legend-item" style="margin-left:12px;color:#aaa;">* Stockouts: rojo&nbsp;=&nbsp;sube, verde&nbsp;=&nbsp;baja</div>
  </div>

  <div class="mvr-wrap">
    <table class="mvr-table">
      <thead>
        <tr>
          <th rowspan="2" style="width:72px;">Secci&oacute;n</th>
          <th rowspan="2" style="width:190px;">KPI</th>
          <th class="mvr-ph" colspan="3" style="width:241px;">Jul&#39;26</th>
          <th class="mvr-ph sep-hdr" colspan="3" style="width:241px;">Q2 FY&#39;26</th>
          <th class="eoy-hdr" rowspan="2" style="width:88px;">EOY<br>Target FY&#39;26</th>
        </tr>
        <tr>
          <th style="text-align:right;width:85px;">Actual</th>
          <th style="text-align:right;width:78px;">YoY</th>
          <th style="text-align:right;width:78px;">vs Plan</th>
          <th class="sep-sub" style="text-align:right;width:85px;">Actual</th>
          <th style="text-align:right;width:78px;">YoY</th>
          <th style="text-align:right;width:78px;">vs Plan</th>
        </tr>
      </thead>
      <tbody>
{table_rows}
      </tbody>
    </table>
  </div>

  <div class="footer">
    <p>Fuentes: DM_VPA_ROADMAP_FINAL (PERIOD=MONTH &#39;Jul 26&#39; &amp; PERIOD=QUARTER &#39;Q2 26&#39;) &middot;
       BT_ORD_ORDERS (NMV ARS) &middot; DM_UE_ESTABILIZADA_PROFITABILITY (VC/DC/BM)</p>
    <p>NMV vs Plan: Jul&#39;26 = {NMV_JUL_VSP} &middot; Q2 = {NMV_Q2_VSP} (planning sheet, fijos). Generado: {ts}</p>
  </div>

</div>

<script>
window.COMP_DATA = {all_data_json};
window.COMP_TS   = {json.dumps(ts)};
</script>
<script>
document.addEventListener('DOMContentLoaded', function() {{
  var el = document.getElementById('comp-ts');
  if (el && window.COMP_TS) el.textContent = window.COMP_TS;
}});
</script>

</body>
</html>"""

    return html


# ─── GIT PUSH ─────────────────────────────────────────────────────────────────

def _push(ts_str):
    repo = OUT_PATH.parent
    cmds = [
        ["git", "-C", str(repo), "add", OUT_PATH.name, Path(__file__).name],
        ["git", "-C", str(repo), "commit", "-m", f"Add Jul26 vs Q2 FY26 comparison HTML: {ts_str}"],
        ["git", "-C", str(repo), "push", "origin", "main"],
    ]
    print("  Subiendo a GitHub ...")
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            if "nothing to commit" in (r.stdout + r.stderr):
                print("  Sin cambios nuevos.")
                return
            print(f"  Error: {r.stderr.strip()}")
            return
    print("  Push exitoso.")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"[{ts}] Generando {OUT_PATH.name} ...")

    print("  Conectando a BigQuery ...")
    try:
        client = bigquery.Client(project=BQ_PROJECT)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # ── Roadmap queries ──────────────────────────────────────────────────────
    print("  Consultando roadmap Jul'26 (MONTH) ...")
    try:
        df_rdm_jul = query_roadmap(client, 'MONTH', 'Jul 26')
        print(f"    {len(df_rdm_jul)} filas.")
    except Exception as e:
        print(f"  WARN roadmap Jul: {e}")
        df_rdm_jul = None

    print("  Consultando roadmap Q2 FY'26 (QUARTER) ...")
    try:
        df_rdm_q2 = query_roadmap(client, 'QUARTER', 'Q2 26')
        print(f"    {len(df_rdm_q2)} filas.")
    except Exception as e:
        print(f"  WARN roadmap Q2: {e}")
        df_rdm_q2 = None

    # ── NMV ARS queries ──────────────────────────────────────────────────────
    print("  Consultando NMV ARS Jul (BT_ORD_ORDERS) ...")
    try:
        df_nmv_jul = query_nmv_jul(client)
        print(f"    {len(df_nmv_jul)} filas.")
    except Exception as e:
        print(f"  WARN NMV Jul: {e}")
        df_nmv_jul = None

    print("  Consultando NMV ARS Q2 (BT_ORD_ORDERS) ...")
    try:
        df_nmv_q2 = query_nmv_q2(client)
        print(f"    {len(df_nmv_q2)} filas.")
    except Exception as e:
        print(f"  WARN NMV Q2: {e}")
        df_nmv_q2 = None

    # ── VC/DC/BM queries ─────────────────────────────────────────────────────
    print("  Consultando VC/DC/BM Jul (DM_UE_ESTABILIZADA) ...")
    try:
        df_ue_jul = query_ue_jul(client)
        print(f"    {len(df_ue_jul)} filas.")
    except Exception as e:
        print(f"  WARN UE Jul: {e}")
        df_ue_jul = None

    print("  Consultando VC/DC/BM Q2 (DM_UE_ESTABILIZADA) ...")
    try:
        df_ue_q2 = query_ue_q2(client)
        print(f"    {len(df_ue_q2)} filas.")
    except Exception as e:
        print(f"  WARN UE Q2: {e}")
        df_ue_q2 = None

    # ── Build data dicts ──────────────────────────────────────────────────────
    print("  Construyendo datos ...")

    rdm_jul = build_rdm(df_rdm_jul, is_jul=True)
    rdm_q2  = build_rdm(df_rdm_q2, is_jul=False)

    nmv_jul = build_nmv(df_nmv_jul, NMV_JUL_VSP)
    nmv_q2  = build_nmv(df_nmv_q2,  NMV_Q2_VSP)

    ue_jul = build_ue(df_ue_jul)
    ue_q2  = build_ue(df_ue_q2)

    jul_d = merge_period(rdm_jul, nmv_jul, ue_jul)
    q2_d  = merge_period(rdm_q2,  nmv_q2,  ue_q2)

    # Print summary
    for period_label, pd in [("Jul'26", jul_d), ("Q2", q2_d)]:
        print(f"  [{period_label}] nmv={pd['nmv']['act']} yoy={pd['nmv']['yoy']} vsp={pd['nmv']['vsp']}")
        print(f"          vc={pd['vc']['act']}  dc={pd['dc']['act']}  bm={pd['bm']['act']}")

    # ── Generate & write HTML ─────────────────────────────────────────────────
    print("  Generando HTML ...")
    html = generate_html(jul_d, q2_d, ts)
    OUT_PATH.write_text(html, encoding='utf-8')
    print(f"  Escrito: {OUT_PATH}  ({len(html):,} bytes)")

    # ── Git push ──────────────────────────────────────────────────────────────
    _push(ts)

    print(f"\n[OK] {OUT_PATH.name} generado. Timestamp: {ts}")


if __name__ == "__main__":
    main()
