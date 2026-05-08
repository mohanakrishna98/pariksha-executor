# Official Playwright image — includes all browser binaries
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Setup app
WORKDIR /app
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port
EXPOSE 10000

# Use Hypercorn (ASGI server) to run the Quart app
# --workers 2 is conservative; tune to your instance size
CMD ["hypercorn", "--bind", "0.0.0.0:10000", "--workers", "2", "--timeout", "180", "app:app"]
