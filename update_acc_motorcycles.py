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

# KPIs to fetch for each sub-segment
MAIN_KPIS = [
    "NMV", "NSI", "NASP", "DC%", "VC%", "BM",
    "Visitas", "CVR (Orders / Visits)", "Buyers", "New Buyers",
    "Frequency",
    "% NMV Clips", "% NMV Affiliates", "# Afiliados",
    "% NMV Buy Box", "CBT Penetration (%NMV)",
    "% NMV FBM", "Stockouts (As % of FBM GMV)",
    "% Promesas en VIP ≤2D ",
    "Benefits Meli Investment %", "Meli Investments in Rebates %",
    "MAds % NMV", "NMV Top Brands KB1",
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
            df = query_roadmap(client, seg, MAIN_KPIS, since=SINCE_FY25)
            # Also get FY26 with plan values
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

    # 7. Update hero card values using a targeted replacement for known patterns
    html = _update_hero_values(html, all_data)

    # 8. Save
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"  ✅ HTML actualizado exitosamente → {HTML_PATH}")
    print(f"  📅 Timestamp: {ts}")

    # 9. Push to GitHub automatically
    _push_to_github(ts)


def _update_hero_values(html, all_data):
    """Update key hero card display values."""
    # This function is a hook for future targeted replacements.
    # Currently the JS data block is the primary data injection mechanism.
    # To make hero cards fully dynamic, add span IDs to the HTML elements
    # and update them here using update_span_ids().
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
