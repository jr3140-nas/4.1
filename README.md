# Work Order Report (Streamlit) — Pixel-Perfect PDF via Headless Chromium

This app lets you:
1. **Upload** an Excel workbook (.xlsx)
2. **Preview** the exact Streamlit layout (charts + table)
3. **Generate** a PDF that **exactly** matches what you see (no layout/color drift)

## Quick Start

```bash
# 1) Create/activate a venv (recommended)
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2) Install deps
pip install -r requirements.txt

# 3) Install the Chromium runtime for Playwright (one-time)
playwright install chromium

# 4) (Optional) Set BASE_URL if not running on localhost:8501
#    Example when reverse proxied or different port:
#    export BASE_URL="http://127.0.0.1:8501"

# 5) Run the app
streamlit run app.py
```

Open the app in your browser (default: http://localhost:8501).

## How it works

- The Streamlit app saves your uploaded Excel to `./uploads/<file_id>.xlsx`.
- The "Printable view" is the **same page** re-opened with `?file_id=...&print=1&w=1400`:
  - `print=1` hides UI chrome (sidebar/toolbar) with CSS
  - `w=1400` fixes container width for deterministic layout
- When you click **Generate Pixel-Perfect PDF**, Playwright launches **headless Chromium**, loads that URL, waits for a
  `data-testid="workorder-ready"` marker, and calls `page.pdf(...)` with background printing enabled. We compute the full
  scroll height and generate **one long page PDF** to avoid pagination artifacts.

## Notes & Tips

- **BASE_URL** must be reachable from the same machine running the app. Default is `http://localhost:8501`.
- If you deploy behind a proxy, set `BASE_URL` accordingly (e.g., `http://your-host:port`).
- The PDF is generated at **device scale factor 2** for sharp text.
- Customize the report visuals in `render_report()` for your data schema (KPIs, charts, column formatting).
- If your Excel has multiple sheets, specify `sheet_name` in `pd.read_excel()`.

## Docker (optional)

A sample Dockerfile is provided. Build & run:

```bash
docker build -t workorder-pdf .
docker run --rm -p 8501:8501 -e BASE_URL="http://localhost:8501" workorder-pdf
```

Then open http://localhost:8501.

## Troubleshooting

- **"Playwright is not installed"** — Make sure you ran:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```
- **Wrong layout in PDF** — Double-check `BASE_URL`, and ensure `w=<px>` in the capture URL matches your page width.
- **Corporate firewall** — The headless browser must fetch the app URL (BASE_URL) locally.
- **Fonts** — Use web-safe fonts or include your fonts via CSS so Chromium matches the screen.
