"""
fix_month_shift.py  -  one-shot: shift table from Jun-MTD to Jul-MTD
Adds Jun 26 column, renames MTD Jun->Jul, resets MTD cells to -- so JS refills.
"""
import re
from pathlib import Path

HTML_PATH = Path(__file__).parent / "acc_motorcycles_kpi_grid.html"
html = HTML_PATH.read_text(encoding="utf-8")

# ── 1. Header row 1: add Jun 26 th before MTD ─────────────────────────────────
html = html.replace(
    '<th class="th-grp-m26" colspan="3">May 26</th>\n      <th class="th-grp-mtd" colspan="3">MTD Jun&rsquo;26</th>',
    '<th class="th-grp-m26" colspan="3">May 26</th>\n      <th class="th-grp-m26" colspan="3">Jun 26</th>\n      <th class="th-grp-mtd" colspan="3">MTD Jul&rsquo;26</th>'
)

# ── 2. Sub-header row 2: add one th-sub trio before th-sub-mtd ────────────────
html = html.replace(
    '<th class="th-sub">Valor</th><th class="th-sub">YoY</th><th class="th-sub">vs Plan</th>\n      <th class="th-sub-mtd">Valor</th><th class="th-sub-mtd">YoY</th><th class="th-sub-mtd">vs Plan</th>',
    '<th class="th-sub">Valor</th><th class="th-sub">YoY</th><th class="th-sub">vs Plan</th>\n      <th class="th-sub">Valor</th><th class="th-sub">YoY</th><th class="th-sub">vs Plan</th>\n      <th class="th-sub-mtd">Valor</th><th class="th-sub-mtd">YoY</th><th class="th-sub-mtd">vs Plan</th>'
)

# ── 3. Section colspan 23 -> 26 ──────────────────────────────────────────────
html = html.replace('colspan="23">', 'colspan="26">')

# ── 4. Data rows: add Jun placeholder + reset MTD ─────────────────────────────
# Use regex with a named group so the replacement is unambiguous:
# Match the blank "May" group immediately before <td class="td-val-mtd">.
# The negative lookahead ensures we don't double-insert.

JUN_PLACEHOLDER = '<td class="td-val">&mdash;</td><td class="td-yoy">&mdash;</td><td class="td-vsp">&mdash;</td>'

def insert_jun_and_reset_mtd(m):
    """
    Called once per row where May(blank) + MTD(any value) is found.
    Inserts Jun placeholder, then resets MTD to blanks.
    """
    return (
        JUN_PLACEHOLDER + '\n      '
        + JUN_PLACEHOLDER + '\n      '
        + '<td class="td-val-mtd">&mdash;</td>'
          '<td class="td-yoy-neu td-val-mtd">&mdash;</td>'
          '<td class="td-vsp td-empty">&mdash;</td>'
    )

# Pattern: blank May group + (any MTD group with any content)
# The MTD group ends before </tr>, so we use [^<]* for cell content.
# Using a negative lookahead after td-val so we don't match if td-val
# is immediately followed by another td-val (which would mean we already inserted).
PATTERN = re.compile(
    r'<td class="td-val">&mdash;</td><td class="td-yoy">&mdash;</td><td class="td-vsp">&mdash;</td>\n      '
    r'<td class="td-val-mtd">.*?</td><td class="[^"]*td-val-mtd[^"]*">.*?</td><td class="[^"]*">.*?</td>',
    re.DOTALL
)

html = PATTERN.sub(insert_jun_and_reset_mtd, html)

# ── 5. Inline all-blank rows: already have the right number of blank groups ──
# These rows use td-yoy-neu class so they didn't match step 4.
# They still have colspan=23 (now fixed in step 3) and no MTD header insert needed.
# But they also need a Jun placeholder. Their structure is all blanks so we add one.
INLINE_PATTERN = re.compile(
    r'(<td class="td-yoy td-yoy-neu">&mdash;</td><td class="td-vsp td-empty">&mdash;</td>)'
    r'\n      <td class="td-val-mtd">&mdash;</td><td class="td-yoy-neu td-val-mtd">&mdash;</td><td class="td-vsp td-empty">&mdash;</td>',
    re.DOTALL
)

def insert_jun_inline(m):
    blank_end = m.group(1)
    # The group matched was the LAST td-yoy-neu before MTD. Add Jun group.
    return (
        blank_end + '\n      '
        '<td class="td-val">&mdash;</td><td class="td-yoy td-yoy-neu">&mdash;</td><td class="td-vsp td-empty">&mdash;</td>'
        '\n      <td class="td-val-mtd">&mdash;</td><td class="td-yoy-neu td-val-mtd">&mdash;</td><td class="td-vsp td-empty">&mdash;</td>'
    )

html = INLINE_PATTERN.sub(insert_jun_inline, html)

# ── 6. JS MONTH_COLS: add Jun 26 ──────────────────────────────────────────────
html = html.replace(
    "var MONTH_COLS = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26'];",
    "var MONTH_COLS = ['Jan 26','Feb 26','Mar 26','Apr 26','May 26','Jun 26'];"
)

# ── 7. Text labels ─────────────────────────────────────────────────────────────
html = html.replace("MTD Jun&rsquo;26", "MTD Jul&rsquo;26")
html = html.replace("MTD Jun'26", "MTD Jul'26")
html = html.replace("Ene-May + MTD Jun", "Ene-Jun + MTD Jul")
html = html.replace("Ene–May + MTD Jun", "Ene–Jun + MTD Jul")
html = html.replace("NASP MTD Jun", "NASP MTD Jul")
html = html.replace("CVR MTD Jun", "CVR MTD Jul")
html = html.replace("NSI MTD Jun", "NSI MTD Jul")
html = html.replace("Visitas MTD Jun", "Visitas MTD Jul")
html = html.replace("MTD NMV May", "MTD NMV Jun")
html = html.replace("Mayo 2026", "Junio 2026")
html = html.replace("Mayo'26", "Jun'26")

HTML_PATH.write_text(html, encoding="utf-8")
print("OK HTML month-shift done: Jun 26 column added, MTD -> Jul'26")
