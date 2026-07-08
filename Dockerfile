# Use a lightweight python image
FROM python:3.13-slim

# Install system dependencies needed for curl-cffi
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Enable unbuffered logging
ENV PYTHONUNBUFFERED=1


# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Expose Hugging Face's default port
EXPOSE 7860

# Start FastAPI server on port 7860
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
