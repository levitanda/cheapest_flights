FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flight_radar/ ./flight_radar/

# Price history lives here; mount a volume or the baselines reset on every
# container replacement and the detector goes blind again.
ENV DATA_DIR=/app/data
VOLUME ["/app/data"]

CMD ["python", "-m", "flight_radar", "watch"]
