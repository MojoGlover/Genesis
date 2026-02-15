# ai_starter - Production Deployment Guide

## 🚀 Quick Deploy Checklist

### Prerequisites
- [ ] Python 3.10+ installed
- [ ] Ollama installed and running
- [ ] Git repository access
- [ ] Target environment ready

### 1. Clone and Install (5 minutes)

```bash
# Clone repository
git clone https://github.com/MojoGlover/Genesis.git
cd Genesis/ai_starter

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# Install package
pip install -e .

# Verify installation
python3 -c "from ai_starter.core.state import TaskQueue; print('✅ Installed')"
```

### 2. Configure Mission (2 minutes)

```bash
# Copy example mission
cp mission.example.txt mission.txt

# Edit mission.txt with your agent's identity
nano mission.txt
```

**Example Mission**:
```
IDENTITY: ProductionBot
ROLE: Autonomous production task executor with RAG-enhanced context retrieval
OWNER: DevOps Team

PRINCIPLES:
- Execute tasks reliably with comprehensive logging
- Learn from failures and adapt behavior
- Maintain high quality standards (>0.8 score)
- Use RAG for context-aware decision making

CONSTRAINTS:
- Never execute destructive operations without verification
- Always validate inputs before tool execution
- Maintain audit trail in memory database
- Respect rate limits and resource quotas
```

### 3. Configure System (3 minutes)

Edit `config.yaml`:

```yaml
ollama:
  base_url: "http://localhost:11434"
  model: "phi3:mini"  # or llama3, mistral, etc.
  temperature: 0.7
  max_tokens: 2048

loop:
  interval_seconds: 30
  max_retries: 3
  task_timeout_seconds: 300

# RAG Configuration
rag:
  chunk_size: 512
  chunk_overlap: 50
  top_k: 5
  similarity_threshold: 0.7

# MCP Servers (optional)
mcp_servers:
  - name: filesystem
    command: uvx
    args: ["mcp-server-filesystem", "/data"]

# Validation
validation:
  verify_outputs: true
  safety_checks: true
  quality_threshold: 0.7

data_dir: "~/.ai_starter"
log_level: "INFO"
```

### 4. Start Ollama (1 minute)

```bash
# Start Ollama server
ollama serve

# Pull required model (in another terminal)
ollama pull phi3:mini

# Verify
ollama list
```

### 5. Test Run (2 minutes)

```bash
# Test with --once mode
python3 -m ai_starter.main --once

# Expected output:
# ✅ Identity loaded
# ✅ Ollama connected
# ✅ Processing task...
# ✅ Task completed successfully
```

### 6. Production Start (1 minute)

```bash
# Run in continuous mode
python3 -m ai_starter.main

# Or with systemd (see below)
sudo systemctl start ai-starter
```

## 🐳 Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy application
COPY ai_starter/ ./ai_starter/
COPY config.yaml mission.txt ./

# Create data directory
RUN mkdir -p /data

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV AI_STARTER_DATA_DIR=/data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s \
  CMD python3 -c "from ai_starter.core.state import TaskQueue; print('ok')"

# Run application
CMD ["python3", "-m", "ai_starter.main"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  ai-starter:
    build: .
    container_name: ai-starter
    restart: unless-stopped
    volumes:
      - ./data:/data
      - ./config.yaml:/app/config.yaml
      - ./mission.txt:/app/mission.txt
    environment:
      - AI_STARTER_LOG_LEVEL=INFO
      - AI_STARTER_OLLAMA__BASE_URL=http://ollama:11434
    depends_on:
      - ollama
    networks:
      - ai-network

  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    volumes:
      - ollama-data:/root/.ollama
    networks:
      - ai-network

volumes:
  ollama-data:

networks:
  ai-network:
```

**Deploy**:
```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f ai-starter

# Stop
docker-compose down
```

## 📦 Systemd Service (Linux)

Create `/etc/systemd/system/ai-starter.service`:

```ini
[Unit]
Description=AI Starter Agent
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=ai-agent
WorkingDirectory=/opt/ai_starter
Environment="PATH=/opt/ai_starter/venv/bin"
ExecStart=/opt/ai_starter/venv/bin/python3 -m ai_starter.main
Restart=on-failure
RestartSec=10s

# Logging
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryLimit=2G
CPUQuota=100%

[Install]
WantedBy=multi-user.target
```

**Setup**:
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable ai-starter

# Start service
sudo systemctl start ai-starter

# Check status
sudo systemctl status ai-starter

# View logs
journalctl -u ai-starter -f
```

## 🔒 Security Best Practices

### 1. Environment Variables

Never commit secrets! Use environment variables:

```bash
export AI_STARTER_OLLAMA__BASE_URL="http://private-ollama:11434"
export AI_STARTER_DATA_DIR="/secure/data"
export AI_STARTER_LOG_LEVEL="WARNING"
```

### 2. File Permissions

```bash
# Restrict config files
chmod 600 mission.txt config.yaml

# Set data directory ownership
chown -R ai-agent:ai-agent ~/.ai_starter
chmod 700 ~/.ai_starter
```

### 3. Network Security

```yaml
# config.yaml - Use internal network
ollama:
  base_url: "http://internal-ollama.local:11434"  # Not public
```

### 4. Enable Validators

```yaml
# config.yaml
validation:
  verify_outputs: true     # Verify LLM outputs
  safety_checks: true      # Check for secrets
  quality_threshold: 0.8   # Minimum quality score
```

## 📊 Monitoring

### Health Check Endpoint

Add to `main.py`:

```python
import asyncio
from pathlib import Path

async def health_check():
    """Check agent health."""
    try:
        # Check Ollama
        if not await llm.is_available():
            return {"status": "unhealthy", "reason": "ollama_unavailable"}
        
        # Check memory
        count = memory.count()
        
        # Check queue
        queue_size = len(queue.tasks)
        
        return {
            "status": "healthy",
            "memories": count,
            "queue_size": queue_size,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### Prometheus Metrics (Future)

```python
from prometheus_client import Counter, Histogram, Gauge

tasks_completed = Counter('ai_starter_tasks_completed', 'Total tasks completed')
task_duration = Histogram('ai_starter_task_duration_seconds', 'Task duration')
queue_size = Gauge('ai_starter_queue_size', 'Current queue size')
```

### Log Aggregation

```bash
# Send logs to centralized logging
journalctl -u ai-starter -f | logger -t ai-starter -n logserver
```

## 🔄 Backup and Recovery

### Backup Script

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/ai_starter"
DATA_DIR="$HOME/.ai_starter"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup
mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/ai_starter_$DATE.tar.gz" "$DATA_DIR"

# Keep last 7 days
find "$BACKUP_DIR" -name "ai_starter_*.tar.gz" -mtime +7 -delete

echo "Backup complete: ai_starter_$DATE.tar.gz"
```

### Recovery

```bash
# Stop service
sudo systemctl stop ai-starter

# Restore data
tar -xzf /backup/ai_starter/ai_starter_20260215_120000.tar.gz -C ~/

# Restart service
sudo systemctl start ai-starter
```

## 🚨 Troubleshooting

### Common Issues

**1. Ollama Connection Failed**
```bash
# Check Ollama status
curl http://localhost:11434/api/tags

# Restart Ollama
sudo systemctl restart ollama
```

**2. Memory Database Locked**
```bash
# Check for stale locks
lsof ~/.ai_starter/memory.db

# Kill stale processes
pkill -f ai_starter
```

**3. High Memory Usage**
```bash
# Check memory
ps aux | grep ai_starter

# Limit memory in systemd
sudo systemctl edit ai-starter
# Add: MemoryLimit=1G
```

**4. Queue Stuck**
```bash
# Inspect queue
python3 -c "
from pathlib import Path
from ai_starter.core.state import TaskQueue
q = TaskQueue.load(Path.home() / '.ai_starter/queue.json')
print(f'Tasks: {len(q.tasks)}, Status: {[t.status for t in q.tasks]})
"

# Clear queue if needed
rm ~/.ai_starter/queue.json
```

## 📈 Scaling

### Horizontal Scaling

Run multiple agents with different missions:

```bash
# Agent 1: High priority tasks
AI_STARTER_DATA_DIR=~/.ai_starter_priority python3 -m ai_starter.main

# Agent 2: Background tasks
AI_STARTER_DATA_DIR=~/.ai_starter_background python3 -m ai_starter.main
```

### Load Balancing

Use a shared queue (Redis/RabbitMQ):

```python
# Future: Add Redis queue backend
class RedisTaskQueue(TaskQueue):
    def __init__(self, redis_url):
        self.redis = Redis.from_url(redis_url)
    
    def next(self) -> Task | None:
        task_data = self.redis.lpop('ai_starter:tasks')
        return Task.model_validate_json(task_data) if task_data else None
```

## 🎯 Production Checklist

- [ ] Mission configured with production identity
- [ ] Config reviewed and secured
- [ ] Ollama running with production model
- [ ] Systemd service configured and enabled
- [ ] Backups configured (daily)
- [ ] Monitoring enabled
- [ ] Logs aggregated
- [ ] Health checks passing
- [ ] Security hardened (permissions, network)
- [ ] Documentation updated for team

---

**ai_starter is production-ready!** 🚀

For support, see:
- README.md - Main documentation
- ENHANCEMENTS.md - Feature guide
- TROUBLESHOOTING.md - Common issues
