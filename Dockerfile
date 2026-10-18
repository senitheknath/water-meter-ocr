FROM python:3.11-slim

WORKDIR /app

# Install minimal OS libraries required for image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies (CPU-optimized PyTorch & EasyOCR)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Cloud Port
ENV PORT=5000
EXPOSE 5000

CMD ["python", "upload_server.py"]
