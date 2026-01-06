# GENESIS Docker Setup

Complete Docker deployment for GENESIS with all services orchestrated and auto-starting.

## 🚀 Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Edit .env with your API keys
nano .env  # or vim, code, etc.

# 3. Build and start everything
docker-compose up -d

# 4. Access Gradio interface
open http://localhost:7860
```

That's it! GENESIS is running with:
- ✅ Gradio web interface (port 7860)
- ✅ Qdrant vector database (port 6333)
- ✅ Auto-restart on failure
- ✅ Persistent data storage

## 📦 What's Included

### Services

**genesis-app**
- Python 3.11 environment
- All dependencies pre-installed
- Gradio server auto-starts
- Hot-reload for development
- Ports: 7860 (web interface)

**genesis-qdrant**
- Qdrant vector database
- Persistent storage volume
- REST API + gRPC
- Ports: 6333 (REST), 6334 (gRPC)

### Networking
- Isolated bridge network
- Service discovery (genesis ↔ qdrant)
- Host access for Ollama models

## 🔧 Configuration

### Environment Variables

Edit `.env` to configure:

```bash
# Required for cloud models
OPENAI_API_KEY=sk-your-key
ANTHROPIC_API_KEY=sk-ant-your-key

# Local Ollama (if running on host)
OLLAMA_BASE_URL=http://host.docker.internal:11434

# Optional overrides
GRADIO_SERVER_PORT=7860
LOG_LEVEL=INFO
```

### Mission Configuration

Your `MISSION.md` is automatically mounted. Edit it on your host:

```bash
nano MISSION.md
# Changes take effect on container restart
docker-compose restart genesis
```

## 📋 Common Commands

### Start/Stop

```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Stop and remove volumes (CAUTION: deletes data)
docker-compose down -v
```

### Logs

```bash
# View all logs
docker-compose logs -f

# View specific service
docker-compose logs -f genesis
docker-compose logs -f qdrant

# Last 100 lines
docker-compose logs --tail=100 genesis
```

### Development

```bash
# Rebuild after code changes
docker-compose up -d --build

# Restart specific service
docker-compose restart genesis

# Execute commands in container
docker-compose exec genesis python
docker-compose exec genesis bash

# View running containers
docker-compose ps
```

### Database Management

```bash
# Backup SQLite database
docker-compose exec genesis cp /app/data/conversations.db /app/data/backup.db

# Access Qdrant admin
open http://localhost:6333/dashboard

# Inspect vector collections
curl http://localhost:6333/collections
```

## 🔍 Troubleshooting

### Container won't start

```bash
# Check logs for errors
docker-compose logs genesis

# Verify .env file exists
ls -la .env

# Check port availability
lsof -i :7860
lsof -i :6333
```

### Can't connect to Ollama

```bash
# Verify Ollama is running on host
curl http://localhost:11434/api/tags

# Check OLLAMA_BASE_URL in .env
grep OLLAMA_BASE_URL .env

# For Linux, use host IP instead of host.docker.internal
# Find your host IP: ip addr show docker0
```

### Permission issues

```bash
# Fix data directory permissions
sudo chown -R $USER:$USER data/ logs/

# Rebuild with no cache
docker-compose build --no-cache
```

### Out of memory

```bash
# Check Docker resources
docker stats

# Increase Docker Desktop memory (Settings → Resources)

# Or limit container memory in docker-compose.yml:
# deploy:
#   resources:
#     limits:
#       memory: 4G
```

## 🏗️ Development Mode

For active development with hot-reload:

```bash
# Start with logs visible
docker-compose up

# Code changes auto-reload (volumes mounted)
# Edit files on host, see changes immediately

# For dependency changes
docker-compose down
docker-compose up --build
```

## 🚢 Production Deployment

### Using Pre-built Image

```bash
# Build production image
docker build -t genesis:latest .

# Tag for registry
docker tag genesis:latest your-registry/genesis:latest

# Push to registry
docker push your-registry/genesis:latest

# Deploy on server
docker pull your-registry/genesis:latest
docker-compose up -d
```

### Environment-Specific Configs

```bash
# Production
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Staging  
docker-compose -f docker-compose.yml -f docker-compose.staging.yml up -d
```

### Secrets Management

Don't commit `.env` to git! Use:
- Docker secrets (Swarm mode)
- Kubernetes secrets
- Cloud provider secret managers (AWS Secrets Manager, GCP Secret Manager)

## 📊 Monitoring

### Health Checks

Built-in health checks for both services:

```bash
# Check service health
docker-compose ps

# Manually trigger health check
docker inspect genesis-app | grep Health -A 10
```

### Metrics

```bash
# Container stats
docker stats genesis-app genesis-qdrant

# Disk usage
docker system df

# Qdrant metrics
curl http://localhost:6333/metrics
```

## 🔒 Security Notes

1. **API Keys**: Never commit `.env` file
2. **Ports**: Firewall ports in production (only expose 7860 if needed)
3. **Updates**: Regularly update base images
4. **Scanning**: Run security scans

```bash
# Scan image for vulnerabilities
docker scan genesis:latest

# Update base image
docker-compose pull
docker-compose up -d --build
```

## 🧹 Cleanup

```bash
# Remove stopped containers
docker-compose down

# Remove volumes (deletes data!)
docker-compose down -v

# Remove images
docker rmi genesis:latest

# Full cleanup (frees disk space)
docker system prune -a --volumes
```

## 📁 Volume Structure

```
GENESIS/
├── data/                      # Mounted to container
│   ├── conversations.db       # SQLite database
│   └── backups/
├── logs/                      # Mounted to container
│   └── genesis.log
└── [docker volumes]
    └── qdrant-storage/        # Vector database data
```

## 🆘 Getting Help

**Container issues:**
```bash
# Full diagnostic
docker-compose logs genesis | tail -50
docker inspect genesis-app
docker-compose exec genesis env
```

**Application issues:**
```bash
# Access container shell
docker-compose exec genesis bash

# Test Python imports
docker-compose exec genesis python -c "import core.mission; print('OK')"

# Check Qdrant connection
docker-compose exec genesis python -c "from qdrant_client import QdrantClient; client = QdrantClient(host='qdrant', port=6333); print(client.get_collections())"
```

## 🎯 Next Steps

- [ ] Configure your API keys in `.env`
- [ ] Customize `MISSION.md` for your agent
- [ ] Add custom tools (see `examples/ADDING_A_TOOL.md`)
- [ ] Set up backups
- [ ] Configure monitoring
- [ ] Deploy to production

---

**Pro Tip**: Use `docker-compose up` (no `-d`) during development to see logs in real-time!
