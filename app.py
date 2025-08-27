# WorkOrderReport4.0 — Streamlit app (no PDF/CSV export)
# Update (robustness):
# - Guard against missing 'Sum of Hours' (creates 0.0 column if absent)
# - Case-insensitive, synonym-based column normalization (e.g., 'Hours', 'Total Hours' → 'Sum of Hours')
# - Ensure 'Production Date' exists (fallback from 'Date' or set NaT)
# - Ensure 'Type' exists (defaults to 'Unspecified') to avoid chart/group errors
# - Keep Cost Center column visible, abbreviated header 'CC'
#
# To run:
#   pip install -r requirements.txt
#   streamlit run app.py

from datetime import datetime
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

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
    "Project": "#9467bd"
}

# Columns to show on dashboard tables (NOTE: includes Cost Center between Type and Description)
DISPLAY_COLUMNS: List[str] = [
    "Name", "Work Order #", "Sum of Hours", "Type",
    "Cost Center",   # inserted here
    "Description", "Problem"
]

# =========================
# Data loading & prep
# =========================
def _norm(s: str) -> str:
    return str(s).strip().lower().replace("#", "number").replace("_", " ")

# Canonical header mapping (case-insensitive, synonyms)
CANON_MAP = {
    "wo number": "Work Order #",
    "work order number": "Work Order #",
    "work order  number": "Work Order #",
    "work order #": "Work Order #",
    "order number": "Work Order #",
    "ordernumber": "Work Order #",
    "workorder": "Work Order #",

    "sum hours": "Sum of Hours",
    "sum of hours": "Sum of Hours",
    "hours": "Sum of Hours",
    "total hours": "Sum of Hours",
    "labor hours": "Sum of Hours",
    "sumhours": "Sum of Hours",

    "prod date": "Production Date",
    "production date": "Production Date",
    "prod date ": "Production Date",
    "prod date  ": "Production Date",
    "prod date  ": "Production Date",
    "prod date   ": "Production Date",
    "prod date    ": "Production Date",
    "prod date     ": "Production Date",
    "prod date      ": "Production Date",
    "prod date       ": "Production Date",
    "prod date        ": "Production Date",
    "prod date         ": "Production Date",
    "prod date          ": "Production Date",
    "prod date           ": "Production Date",
    "prod date            ": "Production Date",
    "prod_date": "Production Date",
    "date": "Production Date",

    "cost center": "Cost Center",
    "costcenter": "Cost Center",

    "craft": "Craft",
    "craft description": "Craft",
    "craftdescription": "Craft",

    "description": "Description",
    "problem": "Problem",
    "problem description": "Problem",

    "name": "Name",
    "employee": "Name",
    "employee name": "Name",
}

def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    new_cols = []
    for c in df.columns:
        key = _norm(c)
        new_cols.append(CANON_MAP.get(key, c))
    df.columns = new_cols
    return df

def load_timeworkbook(xlsx_file) -> pd.DataFrame:
    """Load the uploaded 'Time on Work Order' workbook and normalize columns."""
    df = pd.read_excel(xlsx_file, engine="openpyxl")
    df = _normalize_headers(df)

    # Ensure essential columns exist
    if "Production Date" not in df.columns:
        # Try derive from any column literally called 'Date' (already normalized), else create NaT
        df["Production Date"] = pd.NaT
    if "Sum of Hours" not in df.columns:
        df["Sum of Hours"] = 0.0
    if "Type" not in df.columns:
        df["Type"] = "Unspecified"
    if "Cost Center" not in df.columns:
        # Try Excel column N (index 13) best-effort
        try:
            col_n = df.columns[13]  # 0-based index for 'N'
            df["Cost Center"] = df[col_n]
        except Exception:
            df["Cost Center"] = pd.NA

    # Fallbacks for essential text columns
    for col, default in [
        ("Name", ""), ("Work Order #", ""), ("Description", ""), ("Problem", ""),
    ]:
        if col not in df.columns:
            df[col] = default

    # Conversions / cleanups
    df["Type"] = df["Type"].astype(str).map(lambda x: TYPE_MAP.get(str(x), str(x))).fillna("Unspecified")
    df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)

    # Dates
    df["Production Date"] = pd.to_datetime(df["Production Date"], errors="coerce")
    return df

def prepare_report_data(time_df: pd.DataFrame, selected_date) -> Dict[str, Any]:
    """Filter by date (if available), build per-craft group payloads and a full detail table."""
    df = time_df.copy()

    # Filter by selected date if available
    if "Production Date" in df.columns and not df["Production Date"].dropna().empty and pd.notna(selected_date):
        df = df[df["Production Date"].dt.date == selected_date]

    # Craft column
    craft_col = None
    for cand in ["Craft"]:
        if cand in df.columns:
            craft_col = cand
            break
    if craft_col is None:
        craft_col = "_Craft"
        df[craft_col] = "All Crafts"

    # Ensure numeric hours present (robust to missing)
    if "Sum of Hours" not in df.columns:
        df["Sum of Hours"] = 0.0
    df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)

    groups: List[Tuple[str, Dict[str, Any]]] = []
    for craft_name, g in df.groupby(craft_col, dropna=False):
        g = g.copy()
        # Slice columns for dashboard display — keep order
        present_cols = [c for c in DISPLAY_COLUMNS if c in g.columns]
        detail = g[present_cols].copy() if present_cols else g.copy()
        groups.append((str(craft_name), {"detail": detail}))

    full_detail = pd.concat([p["detail"] for _, p in groups], axis=0) if groups else df[DISPLAY_COLUMNS].copy(errors="ignore")

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
    df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)
    if "Type" not in df.columns:
        df["Type"] = "Unspecified"

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

    # Charts
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

# Date selection (if available), else single "All Data"
if "Production Date" in time_df.columns and not time_df["Production Date"].dropna().empty:
    dates = sorted(pd.to_datetime(time_df["Production Date"]).dt.date.unique())
    date_labels = [datetime.strftime(pd.to_datetime(d), "%m/%d/%Y") for d in dates]
    label_to_date = dict(zip(date_labels, dates))
    selected_label = st.selectbox("Select Production Date", options=date_labels, index=len(date_labels)-1)
    selected_date = label_to_date[selected_label]
else:
    selected_label = "All Data"
    selected_date = pd.NaT
    st.info("No valid 'Production Date' found — showing all data.")

report = prepare_report_data(time_df, selected_date)

# On-screen dashboard & tables (no exports)
st.markdown(f"### Report for {selected_label}")

# Column config — note 'Cost Center' label shown as 'CC'
col_cfg = {
    "Name": st.column_config.TextColumn("Name", width=200),
    "Work Order #": st.column_config.TextColumn("Work Order #", width=110),
    "Sum of Hours": st.column_config.NumberColumn("Sum of Hours", format="%.2f", width=110),
    "Type": st.column_config.TextColumn("Type", width=220),

    "Cost Center": st.column_config.TextColumn("CC", width=140),  # abbreviated header

    "Description": st.column_config.TextColumn("Description", width=320),
    "Problem": st.column_config.TextColumn("Problem", width=420),
}

# Render per-craft sections
for craft_name, payload in report["groups"]:
    st.markdown(f"#### {craft_name}")
    df_detail = payload["detail"]

    # Mini dashboard
    _craft_dashboard_block(df_detail)

    # Table
    st.dataframe(
        df_detail,
        use_container_width=True,
        hide_index=True,
        height=_auto_height(df_detail),
        column_config=col_cfg,
    )
    st.markdown("---")
