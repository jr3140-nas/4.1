# WorkOrderReport4.0 — Streamlit app (robust v2) + Crew filter
# Changes vs previous:
# - Always ensure 'Sum of Hours' and 'Type' exist (prevents KeyError in logs)
# - If 'Type' missing, fill with 'Unknown' prior to groupby and PDF charts
# - CSV export removed; PDF remains 6 columns (no Cost Center)
# - app.py is intended to live at repo ROOT (fixes "main module does not exist")
# - **NEW**: Crew filter selectbox under Production Date (default "All Crews")

import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage
from reportlab.lib.utils import ImageReader

# ----------------- Static mappings -----------------
TYPE_MAP = {
    '0': 'Break In', '1': 'Maintenance Order', '2': 'Material Repair TMJ Order',
    '3': 'Capital Project', '4': 'Urgent Corrective', '5': 'Emergency Order',
    '6': 'PM Restore/Replace', '7': 'PM Inspection', '8': 'Follow Up Maintenance Order',
    '9': 'Standing W.O. - Do not Delete', 'B': 'Marketing', 'C': 'Cost Improvement',
    'D': 'Design Work - ETO', 'E': 'Plant Work - ETO', 'G': 'Governmental/Regulatory',
    'M': 'Model W.O. - Eq Mgmt', 'N': 'Template W.O. - CBM Alerts', 'P': 'Project',
    'R': 'Rework Order', 'S': 'Shop Order', 'T': 'Tool Order', 'W': 'Case',
    'X': 'General Work Request', 'Y': 'Follow Up Work Request', 'Z': 'System Work Request'
}

_TYPE_COLORS = {
    "Break In": "#d62728",
    "Maintenance Order": "#1f77b4",
    "Urgent Corrective": "#ff7f0e",
    "Emergency Order": "#d62728",
    "PM Restore/Replace": "#2ca02c",
    "PM Inspection": "#2ca02c",
    "Follow Up Maintenance Order": "#d4c720",
    "Project": "#9467bd",
    "Unknown": "#777777",
}

DISPLAY_COLUMNS: List[str] = [
    "Name", "Work Order #", "Sum of Hours", "Type",
    "Cost Center",
    "Description", "Problem"
]

# =========================
# Helpers
# =========================
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).strip().lower())

def _ensure_type(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a 'Type' column exists and is mapped if numeric codes."""
    if "Type" not in df.columns:
        df["Type"] = "Unknown"
        return df
    # Map numeric/string codes
    df["Type"] = df["Type"].apply(lambda x: TYPE_MAP.get(str(x), str(x)))
    df["Type"] = df["Type"].replace("", "Unknown")
    return df

def _resolve_hours_column(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a numeric 'Sum of Hours' column exists by renaming or deriving."""
    if "Sum of Hours" in df.columns:
        df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)
        return df

    # Candidate names (case/space/punct insensitive)
    aliases = [
        "sum of hours", "sum hours", "hours", "total hours",
        "hours worked", "time (hrs)", "time hrs", "sum_hours",
        "sumofhours", "tot_hrs", "tot hours", "manhours", "man hours"
    ]
    norm_map = {c: _norm(c) for c in df.columns}
    rev_map = {v: k for k, v in norm_map.items()}

    for ali in aliases:
        key = _norm(ali)
        if key in rev_map:
            src = rev_map[key]
            df.rename(columns={src: "Sum of Hours"}, inplace=True)
            df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)
            return df

    # Fallback: any column containing 'hour' that looks numeric
    hourish = [c for c in df.columns if "hour" in c.lower()]
    for c in hourish:
        series = pd.to_numeric(df[c], errors="coerce")
        if series.notna().sum() > 0:
            df["Sum of Hours"] = series.fillna(0.0)
            return df

    # Last resort: create zero column and warn
    df["Sum of Hours"] = 0.0
    st.warning("No hours column found. Created 'Sum of Hours' = 0.0. Check your export headers.")
    return df

# =========================
# Data loading & prep
# =========================
RENAME_MAP = {
    "WO Number": "Work Order #",
    "Work Order Number": "Work Order #",
    "OrderNumber": "Work Order #",
    "WO #": "Work Order #",
    "WO": "Work Order #",
    "Prod Date": "Production Date",
    "Prod_Date": "Production Date",
}

def _try_rename(df: pd.DataFrame) -> pd.DataFrame:
    # Case-insensitive / trimmed renaming for known keys
    cols = list(df.columns)
    new_cols = []
    for c in cols:
        base = str(c).strip()
        key = base
        for src, dst in RENAME_MAP.items():
            if base.lower() == src.lower():
                key = dst
                break
        new_cols.append(key)
    df.columns = new_cols
    return df

def load_timeworkbook(xlsx_file) -> pd.DataFrame:
    # Read the first sheet with first row as header. If headers look empty, try header=None heuristic.
    df = pd.read_excel(xlsx_file, engine="openpyxl")
    if all(str(c).startswith("Unnamed") for c in df.columns):
        # Try re-reading without header to find the first non-empty row as header
        df_raw = pd.read_excel(xlsx_file, engine="openpyxl", header=None)
        header_row = df_raw.notna().sum(axis=1).idxmax()
        df = pd.read_excel(xlsx_file, engine="openpyxl", header=header_row)

    df = _try_rename(df)

    # Hours and Type
    df = _resolve_hours_column(df)
    df = _ensure_type(df)

    # Production Date
    if "Production Date" in df.columns:
        df["Production Date"] = pd.to_datetime(df["Production Date"], errors="coerce").dt.date
    elif "Date" in df.columns:
        df["Production Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    else:
        df["Production Date"] = pd.NaT

    # Cost Center from header or column N (index 13)
    if "Cost Center" in df.columns:
        df["Cost Center"] = df["Cost Center"].astype(str).str.strip()
    else:
        try:
            col_n = df.columns[13]
            df["Cost Center"] = df[col_n].astype(str).str.strip()
        except Exception:
            df["Cost Center"] = pd.NA

    # Text fallbacks
    for col in ["Name", "Work Order #", "Description", "Problem"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).fillna("")

    # Normalize Crew column name if present in variants
    crew_variants = ["Crew", "crew", "CREW", "Shift/Crew", "Shift - Crew", "Shift_Crew"]
    for variant in crew_variants:
        if variant in df.columns and "Crew" not in df.columns:
            df.rename(columns={variant: "Crew"}, inplace=True)
            break

    return df

def prepare_report_data(time_df: pd.DataFrame, selected_date, selected_crew: str | None) -> Dict[str, Any]:
    df = time_df.copy()

    # Hard guards
    if "Sum of Hours" not in df.columns:
        df = _resolve_hours_column(df)
    if "Type" not in df.columns:
        df = _ensure_type(df)

    # Date filter
    if "Production Date" in df.columns and df["Production Date"].notna().any():
        if pd.notna(selected_date):
            df = df[pd.to_datetime(df["Production Date"], errors="coerce").dt.date == selected_date]

    # Crew filter (only if selected and column exists)
    if selected_crew and selected_crew != "All Crews" and "Crew" in df.columns:
        df = df[df["Crew"].astype(str) == selected_crew]

    # Craft/Department fallback
    craft_col = None
    for cand in ["Craft", "Craft Description", "CraftDescription", "Department", "Location", "Equipment", "PM Number", "PM"]:
        if cand in df.columns:
            craft_col = cand
            break
    if craft_col is None:
        craft_col = "_Craft"
        df[craft_col] = "All Crafts"

    # Numeric hours
    df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)

    groups: List[Tuple[str, Dict[str, Any]]] = []
    for craft_name, g in df.groupby(craft_col, dropna=False):
        g = g.copy()
        # Ensure columns exist
        if "Type" not in g.columns:
            g["Type"] = "Unknown"
        if "Sum of Hours" not in g.columns:
            g["Sum of Hours"] = 0.0
        present_cols = [c for c in DISPLAY_COLUMNS if c in g.columns]
        detail = g[present_cols].copy()
        groups.append((str(craft_name), {"detail": detail}))

    full_detail = pd.concat([p["detail"] for _, p in groups], axis=0) if groups else df[[c for c in DISPLAY_COLUMNS if c in df.columns]].copy()
    return {"groups": groups, "full_detail": full_detail}

# =========================
# Dashboard helpers
# =========================
def _craft_dashboard_block(df_detail: pd.DataFrame):
    if df_detail is None or df_detail.empty:
        return
    df = df_detail.copy()
    if "Sum of Hours" not in df.columns:
        df["Sum of Hours"] = 0.0
    if "Type" not in df.columns:
        df["Type"] = "Unknown"
    df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)

    agg = (df.groupby("Type", dropna=False)["Sum of Hours"]
             .sum()
             .reset_index()
             .rename(columns={"Sum of Hours": "hours"})
             .sort_values("hours", ascending=False))
    total = float(agg["hours"].sum()) if not agg.empty else 0.0
    agg["percent"] = np.where(total > 0, (agg["hours"]/total)*100.0, 0.0)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Hours", f"{total:,.2f}")
    top_type = "-" if agg.empty else str(agg.iloc[0]["Type"])
    top_pct = 0.0 if agg.empty else float(agg.iloc[0]["percent"])
    c2.metric("Top Type", top_type)
    c3.metric("Top Type %", f"{top_pct:.1f}%")

    if agg.empty:
        return

    color_scale = alt.Scale(domain=list(_TYPE_COLORS.keys()), range=list(_TYPE_COLORS.values()))
    base = alt.Chart(agg).mark_bar().encode(
        x=alt.X("Type:N", sort="-y"),
        tooltip=[alt.Tooltip("Type:N"), alt.Tooltip("hours:Q", format=",.2f")]
    )

    st.caption("Hours by Work Order Type")
    st.altair_chart(
        base.encode(y=alt.Y("hours:Q", title="Hours"),
                    color=alt.Color("Type:N", scale=color_scale)),
        use_container_width=True
    )

    st.caption("% of Craft Hours by Type")
    st.altair_chart(
        base.encode(y=alt.Y("percent:Q", title="% of Craft", axis=alt.Axis(format="~s")),
                    color=alt.Color("Type:N", scale=color_scale)),
        use_container_width=True
    )

def _auto_height(df: pd.DataFrame, row_height: int = 28, min_h: int = 220, max_h: int = 680) -> int:
    rows = max(1, len(df))
    h = int(rows * row_height) + 60
    return max(min_h, min(max_h, h))

# =========================
# PDF helpers
# =========================
def _df_for_pdf(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # Guarantee required columns exist for PDF
    for col in ["Name", "Work Order #", "Sum of Hours", "Type", "Description", "Problem"]:
        if col not in out.columns:
            out[col] = "" if col not in ("Sum of Hours",) else 0.0
    pdf_cols = ["Name", "Work Order #", "Sum of Hours", "Type", "Description", "Problem"]
    out = out[pdf_cols]
    out["Type"] = out["Type"].replace("", "Unknown")
    out["Sum of Hours"] = pd.to_numeric(out["Sum of Hours"], errors="coerce").fillna(0.0).map(lambda x: f"{x:.2f}")
    return out

def build_pdf(report: Dict[str, Any], date_label: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                            leftMargin=24, rightMargin=24, topMargin=28, bottomMargin=24)
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontName="Helvetica",
                                fontSize=8, leading=10, wordWrap="CJK", spaceBefore=0, spaceAfter=0)
    header_style = ParagraphStyle("header", parent=styles["Normal"], fontName="Helvetica-Bold",
                                  fontSize=9, leading=11, spaceBefore=0, spaceAfter=0)

    story = []
    title = Paragraph(f"<b>Work Order Reporting</b> — Report for {date_label}", styles["Title"])
    story.append(title); story.append(Spacer(1, 6))

    px_widths = [200, 90, 90, 200, 300, 420]
    page_width, _ = landscape(letter)
    usable = page_width - doc.leftMargin - doc.rightMargin
    scale = usable / sum(px_widths)
    col_widths = [w * scale for w in px_widths]

    header_bg = colors.HexColor("#f0f0f0"); grid_color = colors.HexColor("#d0d0d0")

    for craft_name, payload in report["groups"]:
        story.append(Paragraph(f"<b>{craft_name}</b>", styles["Heading2"]))

        raw = payload["detail"].copy()
        # Guards for charts
        if "Type" not in raw.columns:
            raw["Type"] = "Unknown"
        if "Sum of Hours" not in raw.columns:
            raw["Sum of Hours"] = 0.0

        try:
            tmp = raw.copy()
            tmp["Sum of Hours"] = pd.to_numeric(tmp["Sum of Hours"], errors="coerce").fillna(0.0)
            agg_pdf = (tmp.groupby("Type", dropna=False)["Sum of Hours"].sum()
                         .reset_index()
                         .rename(columns={"Sum of Hours":"hours"})
                         .sort_values("hours", ascending=False))

            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(6.8, 2.6), dpi=150)
            bar_colors = [_TYPE_COLORS.get(str(t), "#1f77b4") for t in agg_pdf["Type"]]
            ax.bar(agg_pdf["Type"], agg_pdf["hours"], color=bar_colors)
            ax.set_title("Hours by Work Order Type")
            ax.set_ylabel("Hours")
            ax.grid(axis="y", linestyle=":", linewidth=0.5)
            for tick in ax.get_xticklabels():
                tick.set_rotation(25)
                tick.set_ha("right")
            fig.tight_layout()

            import io as _io
            buf = _io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            img_reader = ImageReader(buf)
            chart_width = usable * 0.72
            chart_height = chart_width * 0.36
            story.append(RLImage(img_reader, width=chart_width, height=chart_height))
            story.append(Spacer(1, 6))

            bd_headers = [Paragraph("Type", header_style), Paragraph("Hours", header_style)]
            bd_data = [bd_headers]
            for _, r in agg_pdf.iterrows():
                bd_data.append([Paragraph(str(r["Type"]), cell_style),
                                Paragraph(f"{float(r['hours']):.2f}", cell_style)])
            bd_tbl = Table(bd_data, colWidths=[usable*0.45, usable*0.15], repeatRows=1)
            bd_tbl.setStyle(TableStyle([
                ("FONT", (0,0), (-1,-1), "Helvetica"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("BACKGROUND", (0,0), (-1,0), header_bg),
                ("GRID", (0,0), (-1,-1), 0.25, grid_color),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.whitesmoke]),
                ("ALIGN", (0,1), (0,-1), "RIGHT"),
                ("ALIGN", (1,1), (1,-1), "LEFT"),
                ("LEFTPADDING", (0,0), (-1,-1), 4),
                ("RIGHTPADDING", (0,0), (-1,-1), 4),
                ("TOPPADDING", (0,0), (-1,-1), 2),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ]))
            story.append(bd_tbl)
            story.append(Spacer(1, 8))
        except Exception as _e:
            logging.exception("PDF chart embed failed")

        df = _df_for_pdf(raw)
        data: List[List[Any]] = []
        headers = [Paragraph(h, header_style) for h in df.columns]
        data.append(headers)
        for _, row in df.iterrows():
            row_vals = []
            for col in df.columns:
                val = "" if pd.isna(row[col]) else str(row[col])
                if col in ("Work Order #", "Sum of Hours"):
                    row_vals.append(val)
                else:
                    row_vals.append(Paragraph(val, cell_style))
            data.append(row_vals)
        tbl = Table(data, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("FONT", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("BACKGROUND", (0,0), (-1,0), header_bg),
            ("TEXTCOLOR", (0,0), (-1,0), colors.black),
            ("GRID", (0,0), (-1,-1), 0.25, grid_color),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.whitesmoke]),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("ALIGN", (1,1), (1,-1), "RIGHT"),
            ("ALIGN", (2,1), (2,-1), "RIGHT"),
        ]))
        story.append(tbl); story.append(Spacer(1, 8))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()

# =========================
# Streamlit App
# =========================
st.set_page_config(page_title="Work Order Reporting App", layout="wide")
st.title("Work Order Reporting App")

with st.sidebar:
    st.header("Upload file")
    time_file = st.file_uploader("Time on Work Order (.xlsx) – REQUIRED", type=["xlsx"], key="time")

if not time_file:
    st.sidebar.info("⬆️ Upload the **Time on Work Order** export to proceed.")
    st.stop()

try:
    time_df = load_timeworkbook(time_file)
except Exception as e:
    st.sidebar.error(f"File load error: {e}")
    st.stop()

# Production Date select
if "Production Date" in time_df.columns and not pd.Series(time_df["Production Date"]).dropna().empty:
    dates = sorted(pd.to_datetime(time_df["Production Date"]).dt.date.unique())
    date_labels = [datetime.strftime(pd.to_datetime(d), "%m/%d/%Y") for d in dates]
    label_to_date = dict(zip(date_labels, dates))
    selected_label = st.selectbox("Select Production Date", options=date_labels, index=len(date_labels)-1)
    selected_date = label_to_date[selected_label]
else:
    selected_label = "All Data"
    selected_date = pd.NaT
    st.info("No valid 'Production Date' found — showing all data.")

# Crew filter select (NEW) — appears directly under Production Date
selected_crew = None
if "Crew" in time_df.columns:
    # Build options for the currently selected date context to keep the list relevant
    df_for_options = time_df.copy()
    if pd.notna(selected_date):
        df_for_options = df_for_options[pd.to_datetime(df_for_options["Production Date"], errors="coerce").dt.date == selected_date]
    crews = sorted([c for c in df_for_options["Crew"].dropna().astype(str).unique() if str(c).strip() != ""])
    crew_options = ["All Crews"] + crews
    selected_crew = st.selectbox("Filter by Crew", options=crew_options, index=0, help="Default shows all crews.")
else:
    # If no Crew column, keep behavior unchanged
    selected_crew = "All Crews"

report = prepare_report_data(time_df, selected_date, selected_crew)

with st.sidebar:
    st.subheader("Export")
    st.download_button(
        "Generate & Download PDF (Landscape)",
        data=build_pdf(report, selected_label),
        file_name=f"workorder_report_{selected_label.replace('/', '-')}.pdf",
        mime="application/pdf",
    )

st.markdown(f"### Report for {selected_label}")

col_cfg = {
    "Name": st.column_config.TextColumn("Name", width=200),
    "Work Order #": st.column_config.TextColumn("Work Order #", width=90),
    "Sum of Hours": st.column_config.NumberColumn("Sum of Hours", format="%.2f", width=90),
    "Type": st.column_config.TextColumn("Type", width=200),
    "Cost Center": st.column_config.TextColumn("CC", width=120),
    "Description": st.column_config.TextColumn("Description", width=300),
    "Problem": st.column_config.TextColumn("Problem", width=420),
}

for craft_name, payload in report["groups"]:
    st.markdown(f"#### {craft_name}")
    df_detail = payload["detail"]
    _craft_dashboard_block(df_detail)
    st.dataframe(
        df_detail,
        use_container_width=True,
        hide_index=True,
        height=_auto_height(df_detail),
        column_config=col_cfg,
    )
    st.markdown("---")
