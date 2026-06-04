"""
update_acc_motorcycles.py
──────────────────────────────────────────────────────────────────────────────
Actualiza acc_motorcycles_kpi_grid.html con datos frescos de BigQuery.
Fuente: meli-bi-data.WHOWNER.DM_VPA_ROADMAP_FINAL

Uso:
    python update_acc_motorcycles.py

Requiere:
    pip install google-cloud-bigquery pandas
    gcloud auth application-default login   (o service account configurado)

Programado: Windows Task Scheduler, 05:00 AM diario.
──────────────────────────────────────────────────────────────────────────────
"""

import re
import sys
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

# ─── CONFIG ──────────────────────────────────────────────────────────────────
HTML_PATH    = Path(__file__).parent / "acc_motorcycles_kpi_grid.html"
BQ_PROJECT   = "meli-bi-data"
ROADMAP_TABLE = "`meli-bi-data.WHOWNER.DM_VPA_ROADMAP_FINAL`"
AGG1         = "ACC MOTORCYCLES"
SITE         = "MLA"
INICIATIVA   = "ALL"
SINCE_FY26   = "2026-01-01"
SINCE_FY25   = "2025-01-01"

MONTH_ABBR = {
    '01': 'Ene', '02': 'Feb', '03': 'Mar', '04': 'Abr',
    '05': 'May', '06': 'Jun', '07': 'Jul', '08': 'Ago',
    '09': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dic',
}

# KPIs to fetch for each sub-segment (names match DM_VPA_ROADMAP_FINAL KPI column)
MAIN_KPIS = [
    "NMV", "NSI", "NASP", "DC%", "VC%", "BM",
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

AGG2_SEGMENTS = [
    "ALL",
    "MOTORCYCLE HELMETS",
    "MOTORCYCLE ACCESSORIES",
    "MOTORCYCLE REPLACEMENT PARTS",
    "TRANSACTIONAL MOTORCYCLES",
]

# ─── BQ HELPERS ──────────────────────────────────────────────────────────────

def build_kpis_sql(kpis):
    escaped = "', '".join(k.replace("'", "\\'") for k in kpis)
    return f"'{escaped}'"


def query_roadmap(client, agp2, kpis, since=SINCE_FY26):
    sql = f"""
    SELECT
        FECHA_STRING, FECHA, KPI, SECTION, VARIATION,
        VALUE, VALUE_STRING, COLOR_CODING, ORDEN
    FROM {ROADMAP_TABLE}
    WHERE AGG1       = '{AGG1}'
      AND AGG2       = '{agp2}'
      AND PERIOD     = 'MONTH'
      AND SITE       = '{SITE}'
      AND INICIATIVA = '{INICIATIVA}'
      AND FECHA      >= '{since}'
      AND KPI IN ({build_kpis_sql(kpis)})
    ORDER BY ORDEN, KPI, FECHA, VARIATION
    """
    return client.query(sql).to_dataframe()


def pivot_kpi(df, kpi, variation="Actual"):
    """Returns a dict of {fecha_string: value_string} for one KPI/variation."""
    sub = df[(df["KPI"] == kpi) & (df["VARIATION"] == variation)]
    return dict(zip(sub["FECHA_STRING"], sub["VALUE_STRING"]))


def pivot_kpi_num(df, kpi, variation="Actual"):
    """Returns a dict of {fecha_string: float} for one KPI/variation."""
    sub = df[(df["KPI"] == kpi) & (df["VARIATION"] == variation)]
    result = {}
    for _, row in sub.iterrows():
        try:
            result[row["FECHA_STRING"]] = float(row["VALUE"])
        except (ValueError, TypeError):
            result[row["FECHA_STRING"]] = None
    return result


def latest(d):
    """Return the last value in a {month: value} dict, or '—'."""
    if not d:
        return "—"
    return list(d.values())[-1]


def latest_num(d):
    """Return the last numeric value in a {month: float} dict, or None."""
    if not d:
        return None
    vals = [v for v in d.values() if v is not None]
    return vals[-1] if vals else None


def color_status_from_coding(color_coding):
    """Map BigQuery COLOR_CODING → JS-friendly status string."""
    if color_coding == "ABOVE":
        return "above"
    if color_coding == "BELOW":
        return "below"
    if color_coding == "ON TARGET":
        return "on"
    return None


def build_kpi_summary(df26, kpi):
    """
    Build a compact summary dict for one KPI across MTD period.
    Includes string displays AND raw numeric values for JS conditions.
    """
    act_str  = pivot_kpi(df26, kpi, "Actual")
    yoy_str  = pivot_kpi(df26, kpi, "YoY")
    plan_str = pivot_kpi(df26, kpi, "Plan")
    vsp_str  = pivot_kpi(df26, kpi, "vs Plan")
    act_num  = pivot_kpi_num(df26, kpi, "Actual")
    yoy_num  = pivot_kpi_num(df26, kpi, "YoY")
    vsp_num  = pivot_kpi_num(df26, kpi, "vs Plan")

    l_act_n  = latest_num(act_num)
    l_yoy_n  = latest_num(yoy_num)
    l_vsp_n  = latest_num(vsp_num)

    # Use BigQuery COLOR_CODING as the authoritative status source
    # (vs Plan formula in BQ is inverted: negative = Actual ABOVE plan)
    mtd_rows = df26[(df26["KPI"] == kpi) & (df26["VARIATION"] == "Actual") & (df26["FECHA_STRING"] == "MTD")]
    if mtd_rows.empty:
        act_rows = df26[(df26["KPI"] == kpi) & (df26["VARIATION"] == "Actual")]
        mtd_rows = act_rows.tail(1)
    color_coding = mtd_rows.iloc[-1]["COLOR_CODING"] if not mtd_rows.empty else None

    return {
        "actual":          act_str,
        "yoy":             yoy_str,
        "plan":            plan_str,
        "vsp":             vsp_str,
        "latest_actual":   latest(act_str),
        "latest_yoy":      latest(yoy_str),
        "latest_plan":     latest(plan_str),
        "latest_vsp":      latest(vsp_str),
        "latest_actual_n": l_act_n,
        "latest_yoy_n":    l_yoy_n,
        "latest_vsp_n":    l_vsp_n,
        "color_coding":    color_coding,
        "status":          color_status_from_coding(color_coding),
        "yoy_direction":   ("pos" if l_yoy_n and l_yoy_n > 0
                            else "neg" if l_yoy_n and l_yoy_n < 0
                            else "neu"),
    }


def trend_str(actuals, yoys):
    """Build compact trend string: 'Ene: X (+Y%) | Feb: ...'"""
    months = list(actuals.keys())
    parts = []
    for m in months:
        a = actuals.get(m, "—")
        y = yoys.get(m, "")
        y_str = f" ({y})" if y and y != "—" else ""
        parts.append(f"{m}: {a}{y_str}")
    return " | ".join(parts)


# ─── HTML INJECTION ──────────────────────────────────────────────────────────

# The HTML has one auto-generated data block between these markers:
MARKER_START = "<!-- AUTO_DATA_START -->"
MARKER_END   = "<!-- AUTO_DATA_END -->"

# Hero card IDs in the Total tab (each hero-card value has a unique span id)
# Format: (span_id, kpi_name, variation)
HERO_IDS_TOTAL = [
    ("nmv-total-ytd-val",    "NMV",         "Actual", "MTD"),
    ("nmv-total-yoy-mtd",    "NMV",         "YoY",    "MTD"),
    ("nmv-total-vsp-mtd",    "NMV",         "vs Plan","MTD"),
    ("nsi-total-ytd-val",    "NSI",         "Actual", "MTD"),
    ("nsi-total-yoy-mtd",    "NSI",         "YoY",    "MTD"),
    ("nsi-total-vsp-mtd",    "NSI",         "vs Plan","MTD"),
    ("nasp-total-ytd-val",   "NASP",        "Actual", "MTD"),
    ("nasp-total-yoy-prom",  "NASP",        "YoY",    "MTD"),
    ("buyers-total-ytd-val", "Buyers",      "Actual", "MTD"),
    ("buyers-total-yoy-mtd", "Buyers",      "YoY",    "MTD"),
]


def update_span_ids(html, df, id_map):
    """
    Replace <span id="xxx">OLD</span> with fresh BQ values.
    id_map: list of (html_id, kpi, variation, fecha_string)
    """
    for html_id, kpi, variation, fecha in id_map:
        sub = df[(df["KPI"] == kpi) & (df["VARIATION"] == variation)]
        if fecha == "MTD":
            row = sub[sub["FECHA_STRING"] == "MTD"]
        else:
            row = sub[sub["FECHA_STRING"] == fecha]
        if row.empty:
            continue
        value = row.iloc[-1]["VALUE_STRING"]
        # Replace the content between the span tags
        pattern = rf'(<span[^>]*id="{re.escape(html_id)}"[^>]*>)[^<]*(</span>)'
        html = re.sub(pattern, rf'\g<1>{value}\g<2>', html)
    return html


def update_last_update_timestamp(html, ts_str):
    """Update the last-update-ts span."""
    pattern = r'(<span id="last-update-ts"[^>]*>)[^<]*(</span>)'
    return re.sub(pattern, rf'\g<1>{ts_str}\g<2>', html)


def build_data_block(all_data, ts_str):
    """
    Build the AUTO_DATA block with a JS object containing all fresh values.
    This JS object is available in the browser console for debugging.
    """
    lines = [
        MARKER_START,
        "<!-- Generado automáticamente por update_acc_motorcycles.py -->",
        "<!-- NO EDITAR MANUALMENTE — los cambios se sobreescriben en el próximo run -->",
        f"<!-- Última actualización: {ts_str} -->",
        "<script>",
        "window.BQ_LAST_UPDATE = " + repr(ts_str) + ";",
        "window.BQ_DATA = " + _serialize_data(all_data) + ";",
        "</script>",
        MARKER_END,
    ]
    return "\n".join(lines)


def _serialize_data(data):
    """Simple JSON-like serialization."""
    import json
    return json.dumps(data, ensure_ascii=False, indent=2)


def inject_data_block(html, block_content):
    """Replace content between markers, or append before </head> if markers absent."""
    if MARKER_START in html and MARKER_END in html:
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END)
        html = re.sub(pattern, block_content, html, flags=re.DOTALL)
    else:
        # First run: insert just before </head>
        html = html.replace("</head>", block_content + "\n</head>", 1)
    return html


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"[{ts}] Iniciando actualización de {HTML_PATH.name} ...")

    # 1. Connect to BigQuery
    print("  → Conectando a BigQuery ...")
    try:
        client = bigquery.Client(project=BQ_PROJECT)
    except Exception as e:
        print(f"ERROR al conectar con BigQuery: {e}")
        sys.exit(1)

    # 2. Query all segments
    all_data = {}
    for seg in AGG2_SEGMENTS:
        seg_key = seg.lower().replace(" ", "_")
        print(f"  → Consultando AGG2={seg!r} ...")
        try:
            df26 = query_roadmap(client, seg, MAIN_KPIS, since=SINCE_FY26)
        except Exception as e:
            print(f"  ⚠  Error en consulta de {seg}: {e}")
            continue

        seg_data = {}
        for kpi in MAIN_KPIS:
            kpi_key = (kpi.lower()
                       .replace(" ", "_").replace("%", "pct")
                       .replace("(", "").replace(")", "")
                       .replace("/", "_").replace("≤", "lte")
                       .replace("#", "num").replace(".", ""))
            seg_data[kpi_key] = build_kpi_summary(df26, kpi)
            seg_data[kpi_key]["trend"] = trend_str(
                pivot_kpi(df26, kpi, "Actual"),
                pivot_kpi(df26, kpi, "YoY"),
            )
        all_data[seg_key] = seg_data

    # 2b. Replace NMV with local currency (ARS) from BT_ORD_ORDERS
    print("  → Consultando NMV en ARS (BT_ORD_ORDERS) ...")
    for seg in AGG2_SEGMENTS:
        seg_key = seg.lower().replace(" ", "_")
        if seg_key not in all_data:
            continue
        try:
            agg2_filter = None if seg == "ALL" else seg
            df_nmv = query_nmv_ars(client, agg2_filter)
            all_data[seg_key]["nmv"] = build_nmv_ars_summary(df_nmv)
            print(f"    ✓ NMV ARS actualizado para {seg}")
        except Exception as e:
            print(f"  ⚠  Error en NMV ARS para {seg}: {e}")

    # 3. Load existing HTML
    print(f"  → Leyendo {HTML_PATH} ...")
    html = HTML_PATH.read_text(encoding="utf-8")

    # 4. Inject JS data block (for debugging + future JS-driven rendering)
    block = build_data_block(all_data, ts)
    html = inject_data_block(html, block)

    # 5. Update the visible timestamp in the header
    html = update_last_update_timestamp(html, ts)

    # 6. Update span IDs in the Total tab (if they exist)
    if "all" in all_data:
        df_total = query_roadmap(client, "ALL", MAIN_KPIS, since=SINCE_FY26)
        html = update_span_ids(html, df_total, HERO_IDS_TOTAL)

    # 7. Update NMV (B ARS) table cells with correct ARS values and YoY
    html = update_nmv_cells_in_html(html, all_data)

    # 8. Update hero card values using a targeted replacement for known patterns
    html = _update_hero_values(html, all_data)

    # 9. Save
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"  ✅ HTML actualizado exitosamente → {HTML_PATH}")
    print(f"  📅 Timestamp: {ts}")

    # 10. Push to GitHub automatically
    _push_to_github(ts)


def _update_hero_values(html, all_data):
    """Update key hero card display values."""
    # This function is a hook for future targeted replacements.
    # Currently the JS data block is the primary data injection mechanism.
    # To make hero cards fully dynamic, add span IDs to the HTML elements
    # and update them here using update_span_ids().
    return html


def query_nmv_ars(client, agg2_filter=None):
    """Query NMV in local currency (ARS) from BT_ORD_ORDERS."""
    agg2_condition = ""
    if agg2_filter and agg2_filter != "ALL":
        safe = agg2_filter.replace("'", "\\'")
        agg2_condition = f"AND item_domains.DOM_DOMAIN_AGG2 = '{safe}'"

    sql = f"""
    SELECT
        FORMAT_DATE('%Y-%m', orders.ORD_CLOSED_DT) AS month,
        EXTRACT(YEAR FROM orders.ORD_CLOSED_DT) AS year,
        COALESCE(SUM(CASE
            WHEN (NOT COALESCE(orders.ORD_ORDER_MSHOPS_FLG, FALSE))
                AND (orders.ORD_CATEGORY.MARKETPLACE_ID = 'TM')
                AND orders.ORD_GMV_FLG
                AND (NOT COALESCE(orders.ORD_ORDER_PROXIMITY_FLG, FALSE))
            THEN CASE
                WHEN orders.ORD_CLOSED_DT >= CURRENT_DATE - 45 THEN transactional_forecast.F_TGMVELC
                WHEN orders.ORD_TGMV_FLG = true THEN orders.ORD_ITEM.QTY * orders.ORD_ITEM.UNIT_PRICE
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
        AND (
            (orders.ORD_CLOSED_DT >= DATE('{SINCE_FY26}') AND orders.ORD_CLOSED_DT < DATE_ADD(DATE('{SINCE_FY26}'), INTERVAL 1 YEAR))
            OR
            (orders.ORD_CLOSED_DT >= DATE('{SINCE_FY25}') AND orders.ORD_CLOSED_DT < DATE_ADD(DATE('{SINCE_FY25}'), INTERVAL 1 YEAR))
        )
        AND item_domains.DOM_DOMAIN_AGG1 = 'ACC MOTORCYCLES'
        {agg2_condition}
    GROUP BY 1, 2
    ORDER BY 1
    """
    return client.query(sql).to_dataframe()


def build_nmv_ars_summary(df_nmv):
    """Build NMV summary dict from BT_ORD_ORDERS data in billions of ARS."""
    df26 = df_nmv[df_nmv['year'] == 2026].copy()
    df25 = df_nmv[df_nmv['year'] == 2025].copy()

    def to_monthly(df):
        result = {}
        for _, row in df.iterrows():
            month_num = str(row['month']).split('-')[1]
            abbr = MONTH_ABBR.get(month_num, month_num)
            result[abbr] = float(row['nmv_ars']) if row['nmv_ars'] else 0.0
        return result

    act26 = to_monthly(df26)
    act25 = to_monthly(df25)

    def fmt_b(val):
        if val is None or val == 0:
            return "—"
        return f"{val / 1e9:.1f}B"

    actual_str = {m: fmt_b(v) for m, v in act26.items()}

    yoy_str = {}
    for m, v26 in act26.items():
        v25 = act25.get(m)
        if v25 and v25 != 0:
            pct = (v26 / v25 - 1) * 100
            yoy_str[m] = f"{'+' if pct >= 0 else ''}{pct:.0f}%"
        else:
            yoy_str[m] = "—"

    l_act = list(act26.values())[-1] if act26 else None
    l_act_str = fmt_b(l_act)
    l_yoy_str = list(yoy_str.values())[-1] if yoy_str else "—"

    latest_month = list(act26.keys())[-1] if act26 else None
    v25_same = act25.get(latest_month) if latest_month else None
    l_yoy_n = ((l_act / v25_same - 1) * 100
               if l_act and v25_same and v25_same != 0 else None)

    yoy_nums = {}
    for m, v26 in act26.items():
        v25 = act25.get(m)
        yoy_nums[m] = ((v26 / v25 - 1) * 100) if (v25 and v25 != 0) else None

    return {
        "actual":          actual_str,
        "yoy":             yoy_str,
        "plan":            {},
        "vsp":             {},
        "latest_actual":   l_act_str,
        "latest_yoy":      l_yoy_str,
        "latest_plan":     "—",
        "latest_vsp":      "—",
        "latest_actual_n": l_act,
        "latest_yoy_n":    l_yoy_n,
        "latest_vsp_n":    None,
        "color_coding":    None,
        "status":          None,
        "yoy_direction":   ("pos" if l_yoy_n and l_yoy_n > 0
                            else "neg" if l_yoy_n and l_yoy_n < 0
                            else "neu"),
        "trend":           trend_str(actual_str, yoy_str),
        "actual_nums":     dict(act26),
        "yoy_nums":        yoy_nums,
    }


TAB_SEG_MAP = [
    ("tab-total",       "all"),
    ("tab-helmets",     "motorcycle_helmets"),
    ("tab-accessories", "motorcycle_accessories"),
    ("tab-parts",       "motorcycle_replacement_parts"),
    ("tab-trans",       "transactional_motorcycles"),
]

MONTH_ORDER = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]


def update_nmv_cells_in_html(html, all_data):
    """Rewrite NMV (B ARS) table rows with correct ARS values and YoY from BT_ORD_ORDERS."""
    for tab_id, seg_key in TAB_SEG_MAP:
        if seg_key not in all_data or "nmv" not in all_data[seg_key]:
            continue
        nmv = all_data[seg_key]["nmv"]
        actual_nums = nmv.get("actual_nums", {})
        yoy_nums    = nmv.get("yoy_nums", {})
        if not actual_nums:
            continue

        months = [m for m in MONTH_ORDER if m in actual_nums]

        def fmt_b(v):
            return f"{v/1e9:.1f}B" if v else "—"

        def fmt_yoy(y):
            if y is None:
                return "—", "neu"
            return f"{'+' if y >= 0 else ''}{y:.0f}%", ("pos" if y >= 0 else "neg")

        ytd = sum(v for v in actual_nums.values() if v)
        cells = (
            f'<td class="td-val-ytd">{fmt_b(ytd)}</td>'
            f'<td class="td-yoy-neu td-val-ytd">&mdash;</td>'
            f'<td class="td-vsp td-empty td-val-ytd">&mdash;</td>\n      '
        )
        for i, m in enumerate(months):
            v   = actual_nums.get(m, 0)
            yoy, d = fmt_yoy(yoy_nums.get(m))
            if i < len(months) - 1:
                cells += (
                    f'<td class="td-val">{fmt_b(v)}</td>'
                    f'<td class="td-yoy td-yoy-{d}">{yoy}</td>'
                    f'<td class="td-vsp td-empty">&mdash;</td>\n      '
                )
            else:
                cells += (
                    f'<td class="td-val-mtd">{fmt_b(v)}</td>'
                    f'<td class="td-yoy-{d} td-val-mtd">{yoy}</td>'
                    f'<td class="td-vsp td-empty">&mdash;</td>'
                )

        new_row = (
            f'<tr>\n      <td class="td-sec">Overall</td>\n'
            f'      <td class="td-kpi">NMV (B ARS)</td>\n      {cells}\n    </tr>'
        )

        tab_start = html.find(f'id="{tab_id}"')
        tab_end   = html.find('</div><!-- /tab-', tab_start)
        if tab_start == -1 or tab_end == -1:
            continue

        section     = html[tab_start:tab_end]
        nmv_pattern = (r'<tr>\s*<td class="td-sec">Overall</td>\s*'
                       r'<td class="td-kpi">NMV \(B ARS\)</td>.*?</tr>')
        new_section = re.sub(nmv_pattern, new_row, section, count=1, flags=re.DOTALL)
        html = html[:tab_start] + new_section + html[tab_end:]
        print(f"    ✓ NMV celdas HTML actualizadas para {seg_key}")

    return html


def _push_to_github(ts_str):
    """Commit and push the updated HTML to GitHub Pages."""
    repo_dir = HTML_PATH.parent
    file_name = HTML_PATH.name
    commit_msg = f"Auto-update KPI grid: {ts_str}"

    commands = [
        ["git", "-C", str(repo_dir), "add", file_name],
        ["git", "-C", str(repo_dir), "commit", "-m", commit_msg],
        ["git", "-C", str(repo_dir), "push"],
    ]

    print("  → Subiendo a GitHub ...")
    for cmd in commands:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # "nothing to commit" is not a real error
            if "nothing to commit" in result.stdout + result.stderr:
                print("  ℹ  Sin cambios nuevos para commitear.")
                return
            print(f"  ⚠  Error en git: {result.stderr.strip()}")
            return
    print("  ✅ Push a GitHub Pages exitoso.")


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
