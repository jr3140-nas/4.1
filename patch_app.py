#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Patch WorkOrderReport app.py to support **multi-day** selection.
- Replaces st.selectbox(...) with st.multiselect(...).
- Switches selected_label/selected_date to selected_labels/selected_dates.
- Makes prepare_report_data accept a list of dates and filter with .isin(...).
Safe to run multiple times; creates app.py.bak on first run.
"""
from __future__ import annotations
import re, sys, shutil, os
from pathlib import Path

APP = Path("app.py")
if not APP.exists():
    print("[ERROR] app.py not found in current directory.")
    sys.exit(1)

# Read file
src = APP.read_text(encoding="utf-8", errors="ignore")

# Quick detect: already multiselect?
if re.search(r"st\.(multi)?select\(", src) and "selected_dates" in src:
    print("[INFO] It looks like multi-day selection is already enabled. No changes applied.")
    sys.exit(0)

# Backup
bak = APP.with_suffix(".py.bak")
if not bak.exists():
    shutil.copyfile(APP, bak)
    print(f"[INFO] Backup created: {bak.name}")

changed = False

# --- 1) Replace single-date selectbox with multiselect ---
# Pattern variants we saw:
# selected_label = st.selectbox("Select Production Date", options=date_labels, index=len(date_labels) - 1)
# selected_date = label_to_date[selected_label]
selectbox_pat = re.compile(
    r"""
    selected_label\s*=\s*st\.selectbox\(
        [^\)]*?date_labels[^\)]*?
    \)\s*\n
    \s*selected_date\s*=\s*label_to_date\[\s*selected_label\s*\]
    """,
    re.VERBOSE,
)

def replace_selectbox(m):
    return (
        "selected_labels = st.multiselect("
        "\"Select Production Date(s)\", options=date_labels, default=[date_labels[-1]]"
        ")\n"
        "selected_dates = [label_to_date[l] for l in selected_labels]"
    )

src_new, n = selectbox_pat.subn(replace_selectbox, src)
if n == 0:
    # Try a second pattern variant (slightly different whitespace/index expression)
    selectbox_pat2 = re.compile(
        r"""
        selected_label\s*=\s*st\.selectbox\(
            .*?options\s*=\s*date_labels.*?
        \)\s*\n
        \s*selected_date\s*=\s*label_to_date\[\s*selected_label\s*\]
        """,
        re.VERBOSE | re.DOTALL,
    )
    src_new, n = selectbox_pat2.subn(replace_selectbox, src)
if n > 0:
    changed = True
    src = src_new
    print(f"[OK] Replaced single-date selectbox with multiselect ({n} location).")
else:
    print("[WARN] Could not find the single-date selectbox block; skipping that edit.")

# --- 2) Update downstream variable usage in immediate call site ---
# Look for `report = prepare_report_data(..., selected_date)` and replace with `selected_dates`
prep_call = re.compile(r"prepare_report_data\((.*?)selected_date(.*?)\)", re.DOTALL)
src_new, n = prep_call.subn(r"prepare_report_data(\1selected_dates\2)", src)
if n > 0:
    changed = True
    src = src_new
    print(f"[OK] Updated prepare_report_data call to pass selected_dates ({n} location).")
else:
    print("[INFO] No direct prepare_report_data call with selected_date found (may already be updated).")

# --- 3) Modify prepare_report_data signature and inner filter ---
# Change def line param name `selected_date` -> `selected_dates`
def_pat = re.compile(
    r"(def\s+prepare_report_data\s*\(\s*[^)]*?)\bselected_date\b([^)]*\)\s*->\s*[^\:]+:)"
)
src_new, n1 = def_pat.subn(r"\1selected_dates\2", src)

# Inside function: change filter `time_df['Production Date'] == selected_date`
eq_pat = re.compile(
    r"(\s+f\s*=\s*time_df\[\s*time_df\[\s*['\"]Production Date['\"]\s*\]\s*==\s*)selected_date(\s*\]\.copy\(\))"
)
src_new2, n2 = eq_pat.subn(r"\1selected_dates\2", src_new)

# Prepend coercion logic near the start of function body:
# if not isinstance(selected_dates, (list, tuple, set)): selected_dates = [selected_dates]
insert_pat = re.compile(r"(def\s+prepare_report_data\s*\([^\)]*selected_dates[^\)]*\)\s*->[^\:]+:\s*\n)")
def insert_coercion(match):
    head = match.group(1)
    return head + "    # Backward compatible: accept single date or list of dates\n" \
                  "    if not isinstance(selected_dates, (list, tuple, set)):\n" \
                  "        selected_dates = [selected_dates]\n"
src_new3, n3 = insert_pat.subn(insert_coercion, src_new2, count=1)

# Replace equality filter with isin(...) using pd.to_datetime(...).dt.date if needed.
# Upgrade the filter line we already swapped to "selected_dates" into an isin(...)
isin_pat = re.compile(
    r"(\s+f\s*=\s*time_df\[\s*time_df\[\s*['\"]Production Date['\"]\s*\]\s*==\s*selected_dates\s*\]\.copy\(\))"
)
src_new4, n4 = isin_pat.subn(
    "    f = time_df[time_df['Production Date'].isin(selected_dates)].copy()", src_new3
)

if (n1 + n2 + n4) > 0:
    changed = True
    print(f"[OK] Updated prepare_report_data signature ({n1}), equality filter ({n2}), and applied .isin(...) ({n4}).")
else:
    print("[WARN] Could not update prepare_report_data (signature/filter not found).")

# --- 4) Finalize
if changed:
    APP.write_text(src_new4, encoding="utf-8")
    print("[SUCCESS] app.py updated for multi-day selection.")
else:
    print("[NO-OP] No changes applied. Please review warnings above.")
