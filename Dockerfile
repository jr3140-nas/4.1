# Dockerfile — optional container with Playwright & Streamlit
FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Streamlit config
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_PORT=8501 \
    BASE_URL="http://localhost:8501"

COPY . .

# One-time Playwright browser install (Chromium)
RUN playwright install chromium

EXPOSE 8501
CMD ["streamlit", "run", "app.py"]
