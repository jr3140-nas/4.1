#!/usr/bin/env python3
# app.py — Streamlit app with headless Chromium PDF capture using Playwright
# Author: ChatGPT for Jeff Replogle (NAS Mechanical Maintenance Team)

import os
import io
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st
import altair as alt

# Optional dependency only used when generating the PDF
# (This allows the main app to run even if Playwright hasn't been installed yet.)
def _import_playwright_sync_api():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception as e:
        return None

# ---------------------- App Config ----------------------
st.set_page_config(page_title="Work Order Report", layout="wide")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8501")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_DISPLAY_ROWS = 5000  # for charting/table preview performance

# ---------------------- Helpers ----------------------
def set_query_params(**kwargs):
    try:
        st.experimental_set_query_params(**{k: [str(v)] for k, v in kwargs.items() if v is not None})
    except Exception:
        # Back-compat: if Streamlit API changes, silently ignore
        pass

def get_query_params():
    try:
        return {k: v for k, v in st.experimental_get_query_params().items()}
    except Exception:
        return {}

def save_uploaded_file(uploaded_file) -> tuple[str, str]:
    """Save uploaded file to disk as uploads/<file_id>.xlsx"""
    file_id = uuid.uuid4().hex
    dest = os.path.join(UPLOAD_DIR, f"{file_id}.xlsx")
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return file_id, dest

def load_file_by_id(file_id: str) -> pd.DataFrame:
    path = os.path.join(UPLOAD_DIR, f"{file_id}.xlsx")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Uploaded file not found for id={file_id}")
    # Load first sheet by default; if your workbook has a specific sheet, change sheet_name=...
    df = pd.read_excel(path, sheet_name=0, engine="openpyxl")
    return df

def inject_print_css(max_width_px: int = 1400):
    """Hide Streamlit chrome & sidebar, fix container width for deterministic rendering."""
    st.markdown(f"""
        <style>
            header {{ visibility: hidden; height: 0; }}
            [data-testid="stToolbar"] {{ display: none; }}
            [data-testid="stSidebar"] {{ display: none !important; }}
            .block-container {{ max-width: {max_width_px}px; padding-top: 0.5rem; }}
            .stApp {{ background: white; }}
        </style>
    """, unsafe_allow_html=True)

def render_report(df: pd.DataFrame, *, print_mode: bool = False):
    # ---- Title / Context ----
    st.title("Work Order Report")
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not print_mode:
        st.caption("Preview below is exactly what will be sent to PDF.")

    # ---- Simple summary metrics (customize to your schema) ----
    st.subheader("Summary")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Rows", f"{len(df):,}")
    with c2:
        st.metric("Columns", f"{len(df.columns):,}")
    with c3:
        st.metric("Generated", today_str)
    with c4:
        st.metric("File Size", f"{(df.memory_usage(deep=True).sum()/1024):,.0f} KB")

    # ---- Example chart (customize to your data) ----
    # If there is a categorical column named 'Type' or similar, show a bar chart; else, show first numeric column distribution
    chart_area = st.container()
    chart_df = df.copy()
    category_col = None
    for candidate in ["Type", "type", "Category", "category", "WorkType", "Work Type"]:
        if candidate in chart_df.columns:
            category_col = candidate
            break
    if category_col is not None:
        counts = chart_df[category_col].astype("category").value_counts().reset_index()
        counts.columns = [category_col, "Count"]
        chart = alt.Chart(counts).mark_bar().encode(
            x=alt.X(f"{category_col}:N", sort="-y", title=category_col),
            y=alt.Y("Count:Q"),
            tooltip=[category_col, "Count"]
        ).properties(height=300)
        chart_area.altair_chart(chart, use_container_width=True)
    else:
        # Fallback: first numeric column histogram
        num_cols = chart_df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            col = num_cols[0]
            chart = alt.Chart(chart_df.head(MAX_DISPLAY_ROWS)).mark_bar().encode(
                x=alt.X(f"{col}:Q", bin=True, title=col),
                y=alt.Y("count():Q", title="Count"),
                tooltip=[col]
            ).properties(height=300)
            chart_area.altair_chart(chart, use_container_width=True)

    # ---- Styled table ----
    st.subheader("Table")
    st.dataframe(df.head(MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True)

    # ---- "Ready" marker for the PDF renderer ----
    st.markdown('<div id="workorder-ready" data-testid="workorder-ready"></div>', unsafe_allow_html=True)

def _build_capture_url(file_id: str, width_px: int) -> str:
    # print=1 (hides UI in CSS), w=<px> locks the container width so PDF matches exactly
    return f"{BASE_URL}/?file_id={file_id}&print=1&w={width_px}"

def generate_pdf_from_url(capture_url: str, width_px: int = 1400, settle_ms: int = 750) -> bytes:
    sync_playwright = _import_playwright_sync_api()
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(device_scale_factor=2)  # crisp text
        page = context.new_page()
        # Fix viewport width to match our container for deterministic layout
        page.set_viewport_size({"width": width_px, "height": 1000})
        page.goto(capture_url, wait_until="networkidle", timeout=120000)
        try:
            page.wait_for_selector('[data-testid="workorder-ready"]', timeout=120000)
        except Exception:
            # Fail-safe: continue anyway
            pass
        # tiny settle delay for any late charts
        page.evaluate(f"() => new Promise(r => setTimeout(r, {settle_ms}))")
        page.emulate_media(media="screen")

        # Compute full document height to create a single long page PDF
        total_height = page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
        width_in = width_px / 96.0
        height_in = total_height / 96.0

        pdf_bytes = page.pdf(
            print_background=True,
            width=f"{width_in:.2f}in",
            height=f"{height_in:.2f}in",
            margin={"top": "0in", "right": "0in", "bottom": "0in", "left": "0in"},
            scale=1.0,
            display_header_footer=False
        )
        context.close()
        browser.close()
        return pdf_bytes

# ---------------------- UI Flow ----------------------
params = get_query_params()
file_id_param = (params.get("file_id") or [None])[0]
print_flag = (params.get("print") or ["0"])[0] == "1"
width_param = params.get("w", [None])[0]
try:
    fixed_width_px = int(width_param) if width_param else 1400
except Exception:
    fixed_width_px = 1400

if file_id_param:
    # Printable / reproducible view — loads the saved Excel and renders it deterministically
    if print_flag:
        inject_print_css(max_width_px=fixed_width_px)
    try:
        df_loaded = load_file_by_id(file_id_param)
        render_report(df_loaded, print_mode=print_flag)
    except Exception as e:
        st.error(f"Error loading file for id={file_id_param}: {e}")
else:
    st.title("Work Order Report — Upload & Generate PDF")
    st.write("**Steps:** 1) Upload your Excel → 2) Review the on-page visual → 3) Click *Generate PDF* to download an exact match.")

    uploaded = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])
    if uploaded is not None:
        file_id, saved_path = save_uploaded_file(uploaded)
        try:
            df = pd.read_excel(saved_path, sheet_name=0, engine="openpyxl")
        except Exception as e:
            st.error(f"Failed to load Excel: {e}")
            st.stop()

        # Render the report in normal (interactive) mode
        render_report(df, print_mode=False)

        # Printable URL that reproduces the exact view without controls
        capture_url = _build_capture_url(file_id=file_id, width_px=1400)
        with st.expander("Printable view URL (opens without UI controls)", expanded=False):
            st.code(capture_url)

        # Generate PDF button
        st.markdown("---")
        st.subheader("PDF")
        colA, colB = st.columns([1, 1])

        with colA:
            if st.button("Generate Pixel-Perfect PDF", type="primary"):
                try:
                    pdf_bytes = generate_pdf_from_url(capture_url, width_px=1400, settle_ms=750)
                    st.session_state["pdf_bytes"] = pdf_bytes
                    st.success("PDF generated. Use the Download button.")
                except Exception as e:
                    st.error(f"PDF generation failed: {e}\n\n"
                             "Tip: Ensure Playwright is installed and BASE_URL is reachable by this machine.")
        with colB:
            if "pdf_bytes" in st.session_state:
                fname = f"workorder_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                st.download_button(
                    "Download PDF",
                    data=st.session_state["pdf_bytes"],
                    file_name=fname,
                    mime="application/pdf",
                    use_container_width=True
                )

    # Helpful troubleshooting box
    with st.expander("Troubleshooting", expanded=False):
        st.markdown(f"""
        - **'Playwright is not installed'** → Run:
            ```bash
            pip install -r requirements.txt
            playwright install chromium
            ```
        - **Blank PDF or wrong layout** → Check that **BASE_URL** points to this app (current default: `{BASE_URL}`).
        - **Corporate proxy / firewall** → Ensure the machine can access `{BASE_URL}` from itself.
        - **Fonts** → Use web-safe fonts or include @font-face in your theme so Chromium matches your screen.
        """)
