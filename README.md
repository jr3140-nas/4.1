# WorkOrderReport — Multi‑Day Date Selection Patch

This package *patches* your existing **Streamlit** app in `app.py` so users can select **multiple Production Dates** instead of a single date. Nothing else is changed.

## What it does
- Replaces the single‑date `st.selectbox(...)` with a **multi‑select** (`st.multiselect(...)`).
- Adjusts the selection variables from `selected_label`/`selected_date` to `selected_labels`/`selected_dates` (a list).
- Updates the filtering logic from `== selected_date` to `.isin(selected_dates)`.
- Extends `prepare_report_data(...)` to accept either a single date or a list of dates (backward compatible).

## How to use

1) **Back up your repo** (or make a new branch).
2) Copy this folder’s contents anywhere on your machine.
3) Run the patcher from the root of your repo (the folder that contains `app.py`):  
   ```bash
   python patch_app.py
   ```
4) Commit the changes and push to a new GitHub repo if desired.

> If your code already supports multi‑day selection, the patcher will detect this and do nothing.

## Safety
- The patcher creates a backup: `app.py.bak`.
- All edits are **targeted regex replacements** and are idempotent (running multiple times is safe).

## Notes
- The patch targets the date‑picker section and `prepare_report_data`. It uses defensive regexes that match the exact patterns we saw in your repo history.
- If you keep a slightly different naming, the script still tries alternative patterns.
