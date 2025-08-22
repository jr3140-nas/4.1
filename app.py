
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Work Order Cost Breakdown", layout="wide")
st.title("Work Order Cost Breakdown")

with st.sidebar:
    st.header("Upload")
    time_file = st.file_uploader("Time on Work Order (.xlsx) – REQUIRED", type=["xlsx"], key="time")
    st.markdown("---")
    st.header("Rates")
    labor_rate = st.number_input(
        "Labor rate ($/hr)",
        min_value=0.0,
        value=float(st.session_state.get("labor_rate", 75.00)),
        step=1.00,
        format="%.2f",
        key="labor_rate"
    )
    st.caption("This rate only affects the Breakdown tables below.")

st.markdown("### Instructions")
st.markdown("""
- Upload an Excel file with at least the columns **Type** and **Hours** (case-insensitive).
- The app will aggregate hours by **Type** and compute **Cost = Hours × Rate** for the **Breakdown** tables.
""")

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Lowercase & strip columns for robust matching
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    # Try to normalize "hours" column variants
    if "hours" not in df.columns:
        # common alternates
        for alt in ["hrs", "time_hours", "time", "duration_hours"]:
            if alt in df.columns:
                df["hours"] = df[alt]
                break
    # Ensure presence
    if "type" not in df.columns or "hours" not in df.columns:
        raise ValueError("Input must contain columns 'Type' and 'Hours' (case-insensitive).")
    return df

def _format_currency(x):
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return x

def _style_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    # Return as-is; Streamlit will display. (Optional: could add background gradients)
    return df

def _aggregate_by_type(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("type", dropna=False, as_index=False)["hours"].sum()
    g = g.rename(columns={"type": "Type", "hours": "Hours"})
    g["Hours"] = g["Hours"].astype(float).round(2)
    return g

if time_file is None:
    st.info("Upload a .xlsx file to get started. A sample is provided below.")
else:
    try:
        raw = pd.read_excel(time_file)
        norm = _normalize_columns(raw)
        agg = _aggregate_by_type(norm)

        # --- Breakdown Table: Hours & Cost ---
        _rate = float(st.session_state.get("labor_rate", 0.0))
        breakdown_df = agg.copy()
        breakdown_df["Cost"] = (breakdown_df["Hours"] * _rate).round(2)
        # Display formatting
        display_df = breakdown_df.copy()
        display_df["Cost"] = display_df["Cost"].map(_format_currency)

        st.subheader("Breakdown (Hours & Cost)")
        st.dataframe(_style_breakdown(display_df), use_container_width=True, hide_index=True)

        # Totals
        total_hours = float(agg["Hours"].sum())
        total_cost = float((agg["Hours"] * _rate).sum())
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Hours", f"{total_hours:,.2f}")
        with col2:
            st.metric("Total Cost", _format_currency(total_cost))

        st.caption("Note: Changing the labor rate in the sidebar updates the **Cost** column live.")

        # Optional: Download results
        @st.cache_data
        def _to_xlsx_bytes(df1: pd.DataFrame) -> bytes:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df1.to_excel(writer, index=False, sheet_name="Breakdown")
            buf.seek(0)
            return buf.getvalue()

        xls_bytes = _to_xlsx_bytes(breakdown_df)
        st.download_button("Download Breakdown (xlsx)", data=xls_bytes, file_name="breakdown_with_cost.xlsx")

    except Exception as e:
        st.error(f"Error reading file: {e}")

st.markdown("---")
st.caption("© 2025 Work Order Cost Breakdown App")
