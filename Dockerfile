FROM python:3.11-slim

WORKDIR /app

# Install Chrome dependencies, Chrome, cron, and Xvfb for headless display
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    cron \
    tzdata \
    xvfb \
    # Chrome dependencies
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome (using modern gpg method instead of deprecated apt-key)
RUN wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get update && \
    apt-get install -y /tmp/google-chrome.deb || apt-get install -fy && \
    rm /tmp/google-chrome.deb && \
    rm -rf /var/lib/apt/lists/*

# Set timezone (adjust as needed)
ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY book_tee_time.py .
COPY *.sh ./
COPY *.py ./

# Create directories for logs and screenshots
RUN mkdir -p /app/logs /app/screenshots

# Create cron job file for Saturday 6:50 AM (waits until 7 AM to book)
# 50 6 * * 6 = 6:50 AM every Saturday
RUN echo "50 6 * * 6 cd /app && DISPLAY=:99 HEADLESS=true /usr/bin/python3 /app/book_tee_time.py >> /app/logs/cron_\$(date +\%Y-\%m-\%d).log 2>&1" > /etc/cron.d/bhawk-booking && \
    chmod 0644 /etc/cron.d/bhawk-booking && \
    crontab /etc/cron.d/bhawk-booking

# Create entrypoint script
RUN echo '#!/bin/bash\n\
# Export environment variables for cron\n\
printenv | grep -v "no_proxy" >> /etc/environment\n\
\n\
# Start Xvfb virtual display\n\
Xvfb :99 -screen 0 1920x1080x24 &\n\
export DISPLAY=:99\n\
\n\
# Start cron in foreground\n\
echo "Starting Black Hawk booking container with cron..."\n\
echo "Cron schedule: Saturday 6:50 AM (waits until 7 AM to book Sunday tee times)"\n\
cron -f' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Environment variables
ENV HEADLESS=true
ENV DISPLAY=:99

ENTRYPOINT ["/app/entrypoint.sh"]
