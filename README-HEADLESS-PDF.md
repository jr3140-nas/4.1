# Headless Chromium "Screen-Exact" PDF — Addendum

This patch keeps your UI and existing ReportLab export intact and adds a **pixel-perfect** PDF that matches exactly what is on screen.

## One-time setup
```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage
- Upload your Excel, pick a date, view the dashboard.
- In the sidebar, under **Screen-Exact PDF**, click **Generate Pixel-Perfect PDF**, then **Download**.
- The app saves the uploaded file to `./uploads/<id>.xlsx` and uses a reproducible URL with `?file_id=...&print=1&w=1400` for capture.

## Environment
- If the app is not at `http://localhost:8501`, set:
  - macOS/Linux: `export BASE_URL="http://127.0.0.1:8501"`
  - Windows (PowerShell): `$env:BASE_URL="http://127.0.0.1:8501"`

## Notes
- Output is a **single long-page PDF** (no pagination artifacts).
- Colors/backgrounds preserved (`media='screen'`, `printBackground=True`).
- Crisp text (device scale factor 2).
- To remove this feature, delete the helper block at the top, the sidebar "Screen-Exact PDF" section, and the final `add_ready_marker()` line.
