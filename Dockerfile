# Updated to the version required by the error message
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

# 1. Install standard Google Chrome (so Selenium still works)
RUN apt-get update && apt-get install -y wget gnupg \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable

# 2. Setup App
WORKDIR /app
COPY . .

# 3. Install Python Dependencies
RUN pip install -r requirements.txt

# 4. Run App
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
