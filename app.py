# WorkOrderReport4.0 — Streamlit app (no PDF/CSV export)
# Changes:
# - Removed all PDF and CSV export features
# - Kept Cost Center column between Type and Description; abbreviated header to 'CC'
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
RENAME_MAP = {
    "WO Number": "Work Order #",
    "Work Order Number": "Work Order #",
    "OrderNumber": "Work Order #",
    "Sum Hours": "Sum of Hours",
    "Hours": "Sum of Hours",
    "Prod Date": "Production Date",
    "Prod_Date": "Production Date",
}

def _try_rename(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c: RENAME_MAP.get(c, c) for c in df.columns}
    df = df.rename(columns=cols)
    return df

def load_timeworkbook(xlsx_file) -> pd.DataFrame:
    """Load the uploaded 'Time on Work Order' workbook and normalize columns."""
    df = pd.read_excel(xlsx_file, engine="openpyxl")
    df = _try_rename(df)

    # Standardize key columns if present
    if "Type" in df.columns:
        df["Type"] = df["Type"].astype(str).map(lambda x: TYPE_MAP.get(x, x)).fillna("")
    if "Sum of Hours" in df.columns:
        df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)

    # Derive Production Date if possible
    if "Production Date" in df.columns:
        df["Production Date"] = pd.to_datetime(df["Production Date"], errors="coerce").dt.date
    elif "Date" in df.columns:
        df["Production Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    else:
        # allow app to run without date — single bucket
        df["Production Date"] = pd.NaT

    # --- Cost Center from column "N" (index 13) or existing header ---
    if "Cost Center" in df.columns:
        df["Cost Center"] = df["Cost Center"].astype(str).str.strip()
    else:
        try:
            col_n = df.columns[13]  # 0-based index; Excel column N
            df["Cost Center"] = df[col_n].astype(str).str.strip()
        except Exception:
            df["Cost Center"] = pd.NA

    # Fallbacks for essential text columns
    for col in ["Name", "Work Order #", "Description", "Problem"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).fillna("")

    return df

def prepare_report_data(time_df: pd.DataFrame, selected_date) -> Dict[str, Any]:
    """Filter by date (if available), build per-craft group payloads and a full detail table."""
    df = time_df.copy()

    # Filter by selected date if column has real dates
    if pd.api.types.is_datetime64_any_dtype(pd.to_datetime(df["Production Date"], errors="coerce")):
        if pd.notna(selected_date):
            df = df[pd.to_datetime(df["Production Date"], errors="coerce").dt.date == selected_date]

    # Establish a craft grouping column if present
    craft_col = None
    for cand in ["Craft", "Craft Description", "CraftDescription"]:
        if cand in df.columns:
            craft_col = cand
            break
    if craft_col is None:
        craft_col = "_Craft"
        df[craft_col] = "All Crafts"

    # Ensure numeric hours for aggregation
    df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)

    groups: List[Tuple[str, Dict[str, Any]]] = []
    for craft_name, g in df.groupby(craft_col, dropna=False):
        g = g.copy()
        # Slice columns for dashboard display — keep order
        present_cols = [c for c in DISPLAY_COLUMNS if c in g.columns]
        detail = g[present_cols].copy()
        groups.append((str(craft_name), {"detail": detail}))

    full_detail = pd.concat([p["detail"] for _, p in groups], axis=0) if groups else df[DISPLAY_COLUMNS].copy()

    return {"groups": groups, "full_detail": full_detail}

# =========================
# Dashboard helpers
# =========================
def _craft_dashboard_block(df_detail: pd.DataFrame):
    if df_detail is None or df_detail.empty:
        return
    df = df_detail.copy()
    if "Sum of Hours" not in df.columns:
        return
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
    "Work Order #": st.column_config.TextColumn("Work Order #", width=90),
    "Sum of Hours": st.column_config.NumberColumn("Sum of Hours", format="%.2f", width=90),
    "Type": st.column_config.TextColumn("Type", width=200),

    "Cost Center": st.column_config.TextColumn("CC", width=120),  # abbreviated header

    "Description": st.column_config.TextColumn("Description", width=300),
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
