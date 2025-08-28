# WorkOrderReport4.0 — Streamlit app (robust v2)
# (Baseline from repo) — patched to add headless Chromium PDF print without redesigning UI.

import io
import logging
import os
import re
import uuid
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
# Minimal PDF-print helpers (patch)
# =========================
BASE_URL = os.getenv("BASE_URL", "http://localhost:8501")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
FIXED_WIDTH_PX = 1400

def _st_set_query_params(**kwargs):
    try:
        st.experimental_set_query_params(**{k: [str(v)] for k, v in kwargs.items() if v is not None})
    except Exception:
        pass

def _st_get_query_params():
    try:
        return {k: v for k, v in st.experimental_get_query_params().items()}
    except Exception:
        return {}

def inject_print_css(max_width_px: int = FIXED_WIDTH_PX):
    st.markdown(f"""
        <style>
            header {{ visibility: hidden; height: 0; }}
            [data-testid="stToolbar"] {{ display:none; }}
            [data-testid="stSidebar"] {{ display:none !important; }}
            .block-container {{ max-width:{max_width_px}px; padding-top: 0.5rem; }}
            .stApp {{ background:white; }}
        </style>
    """, unsafe_allow_html=True)

def add_ready_marker():
    st.markdown('<div id="pdf-ready" data-testid="pdf-ready"></div>', unsafe_allow_html=True)

def _save_uploaded_file(uploaded_file) -> tuple[str, str]:
    file_id = uuid.uuid4().hex
    dest = os.path.join(UPLOAD_DIR, f"{file_id}.xlsx")
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return file_id, dest

def _load_saved_file(file_id: str):
    import pandas as pd
    p = os.path.join(UPLOAD_DIR, f"{file_id}.xlsx")
    if not os.path.exists(p):
        raise FileNotFoundError(f"Saved file not found: {file_id}")
    return pd.read_excel(p, engine="openpyxl")

def capture_url_for_current_view(**state):
    q = "&".join([f"{k}={v}" for k,v in state.items() if v is not None])
    return f"{BASE_URL}/?print=1&w={FIXED_WIDTH_PX}" + (f"&{q}" if q else "")

def generate_pdf_via_chromium(capture_url: str, width_px: int = FIXED_WIDTH_PX, settle_ms: int = 750) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("Playwright not available. Run:\n  pip install playwright\n  playwright install chromium") from e
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(device_scale_factor=2)
        page = context.new_page()
        page.set_viewport_size({"width": width_px, "height": 1000})
        page.goto(capture_url, wait_until="networkidle", timeout=120000)
        try:
            page.wait_for_selector('[data-testid="pdf-ready"]', timeout=120000)
        except Exception:
            pass
        page.evaluate(f"() => new Promise(r => setTimeout(r, {settle_ms}))")
        page.emulate_media(media="screen")
        total_height = page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
        width_in = width_px / 96.0
        height_in = total_height / 96.0
        pdf = page.pdf(
            print_background=True,
            width=f"{width_in:.2f}in",
            height=f"{height_in:.2f}in",
            margin={"top":"0in","right":"0in","bottom":"0in","left":"0in"},
            scale=1.0,
            display_header_footer=False,
        )
        context.close()
        browser.close()
        return pdf

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
    df["Type"] = df["Type"].apply(lambda x: TYPE_MAP.get(str(x), str(x)))
    df["Type"] = df["Type"].replace("", "Unknown")
    return df

def _resolve_hours_column(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a numeric 'Sum of Hours' column exists by renaming or deriving."""
    if "Sum of Hours" in df.columns:
        df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)
        return df
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
    hourish = [c for c in df.columns if "hour" in c.lower()]
    for c in hourish:
        series = pd.to_numeric(df[c], errors="coerce")
        if series.notna().sum() > 0:
            df["Sum of Hours"] = series.fillna(0.0)
            return df
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
    df = pd.read_excel(xlsx_file, engine="openpyxl")
    if all(str(c).startswith("Unnamed") for c in df.columns):
        df_raw = pd.read_excel(xlsx_file, engine="openpyxl", header=None)
        header_row = df_raw.notna().sum(axis=1).idxmax()
        df = pd.read_excel(xlsx_file, engine="openpyxl", header=header_row)
    df = _try_rename(df)
    df = _resolve_hours_column(df)
    df = _ensure_type(df)

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

    for col in ["Name", "Work Order #", "Description", "Problem"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).fillna("")
    return df

def prepare_report_data(time_df: pd.DataFrame, selected_date) -> Dict[str, Any]:
    df = time_df.copy()
    if "Sum of Hours" not in df.columns:
        df = _resolve_hours_column(df)
    if "Type" not in df.columns:
        df = _ensure_type(df)

    if "Production Date" in df.columns and df["Production Date"].notna().any():
        if pd.notna(selected_date):
            df = df[pd.to_datetime(df["Production Date"], errors="coerce").dt.date == selected_date]

    craft_col = None
    for cand in ["Craft", "Craft Description", "CraftDescription", "Department", "Location", "Equipment", "PM Number", "PM"]:
        if cand in df.columns:
            craft_col = cand
            break
    if craft_col is None:
        craft_col = "_Craft"
        df[craft_col] = "All Crafts"

    df["Sum of Hours"] = pd.to_numeric(df["Sum of Hours"], errors="coerce").fillna(0.0)

    groups: List[Tuple[str, Dict[str, Any]]] = []
    for craft_name, g in df.groupby(craft_col, dropna=False):
        g = g.copy()
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
# PDF (existing ReportLab builder left intact)
# =========================
def _df_for_pdf(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
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

params = _st_get_query_params()
print_mode = (params.get("print") or ["0"])[0] == "1"
width_param = params.get("w", [None])[0]
try:
    fixed_width_px = int(width_param) if width_param else FIXED_WIDTH_PX
except Exception:
    fixed_width_px = FIXED_WIDTH_PX
if print_mode:
    inject_print_css(max_width_px=fixed_width_px)

with st.sidebar:
    st.header("Upload file")
    time_file = st.file_uploader("Time on Work Order (.xlsx) – REQUIRED", type=["xlsx"], key="time")

# If we’re in print mode with ?file_id=..., load from disk for reproducible render.
file_id_param = (params.get("file_id") or [None])[0]
if print_mode and file_id_param:
    try:
        time_df = _load_saved_file(file_id_param)
    except Exception as e:
        st.error(f"Failed to load saved file for printing: {e}")
        st.stop()
else:
    if not time_file:
        st.sidebar.info("⬆️ Upload the **Time on Work Order** export to proceed.")
        st.stop()
    try:
        time_df = load_timeworkbook(time_file)
    except Exception as e:
        st.sidebar.error(f"File load error: {e}")
        st.stop()

# Date selection (unchanged)
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

report = prepare_report_data(time_df, selected_date)

# Sidebar export (existing ReportLab PDF)
with st.sidebar:
    st.subheader("Export")
    st.download_button(
        "Generate & Download PDF (ReportLab)",
        data=build_pdf(report, selected_label),
        file_name=f"workorder_report_{selected_label.replace('/', '-')}.pdf",
        mime="application/pdf",
    )

# New: Pixel-perfect PDF (Headless Chromium)
with st.sidebar:
    st.subheader("Screen-Exact PDF")
    # If a file was uploaded in this session, persist it to disk and encode file_id in the capture URL.
    current_file_id = None
    if time_file is not None and not (print_mode and file_id_param):
        try:
            current_file_id, saved_path = _save_uploaded_file(time_file)
        except Exception:
            current_file_id = None
    file_for_url = file_id_param or current_file_id
    capture_url = capture_url_for_current_view(
        date=selected_label,
        file_id=file_for_url
    )
    if st.button("Generate Pixel-Perfect PDF", type="primary"):
        try:
            pdf_bytes = generate_pdf_via_chromium(capture_url, width_px=fixed_width_px, settle_ms=750)
            st.session_state["pixel_pdf_bytes"] = pdf_bytes
            st.success("Screen-exact PDF ready. Click Download.")
        except Exception as e:
            st.error(f"Chromium print failed: {e}\n"
                     "Tip: ensure Playwright is installed and BASE_URL points to this app.")
    if "pixel_pdf_bytes" in st.session_state:
        fname2 = f"workorder_screen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        st.download_button("Download Screen-Exact PDF", st.session_state["pixel_pdf_bytes"], file_name=fname2, mime="application/pdf")

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

# Ready marker for the print service (must be LAST)
add_ready_marker()
