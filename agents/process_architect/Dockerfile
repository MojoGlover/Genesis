FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caches until requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Persistent data — mount a volume here
ENV DATA_DIR=/data

# Ollama runs as a sidecar — point at its container hostname
ENV OLLAMA_API_URL=http://ollama:11434/api

# Cloud fallback keys — inject at runtime, never baked in
ENV ANTHROPIC_API_KEY=""
ENV OPENAI_API_KEY=""

# PlugOps bus — inject at runtime
ENV PLUGOPS_URL=""
ENV PLUGOPS_AGENT=""

EXPOSE 5001

CMD ["python", "main.py"]
