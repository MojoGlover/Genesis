# GENESIS Docker Setup Files

## 📦 What You Just Downloaded

Complete Docker deployment setup for GENESIS with auto-starting services.

## 📁 File Placement

Place these files in your **GENESIS root directory**:

```
GENESIS/
├── Dockerfile                    # ← Main app container definition
├── docker-compose.yml            # ← Orchestration (dev mode)
├── docker-compose.prod.yml       # ← Production overrides
├── .dockerignore                 # ← Build exclusions
├── .env.example                  # ← Environment template
├── docker-start.sh               # ← Quick start script
└── docker/
    ├── README.md                 # ← Full documentation
    └── .gitignore-additions      # ← Add to your .gitignore
```

## 🚀 Quick Start (3 Steps)

**1. Copy files to your GENESIS directory:**
```bash
cd ~/path/to/GENESIS
# Move all downloaded files here
```

**2. Run the setup script:**
```bash
chmod +x docker-start.sh
./docker-start.sh
```

**3. Edit .env with your API keys:**
```bash
nano .env
# Add: OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.
```

**Then start:**
```bash
docker-compose up -d
```

**Access at:** http://localhost:7860

## 🎯 What This Gives You

✅ **Complete Stack:**
- GENESIS app with Gradio interface (auto-starts)
- Qdrant vector database
- Persistent storage
- Hot-reload for development

✅ **One-Command Deploy:**
```bash
docker-compose up -d
```

✅ **Production Ready:**
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

✅ **Easy Management:**
```bash
docker-compose logs -f          # View logs
docker-compose restart genesis  # Restart app
docker-compose down            # Stop everything
```

## 📋 Before First Run

1. **Set API Keys** (in `.env`):
   - OPENAI_API_KEY
   - ANTHROPIC_API_KEY
   - OLLAMA_BASE_URL (if using local models)

2. **Review MISSION.md**:
   - Your mission file is auto-mounted
   - Edit on host, restart container to apply

3. **Check ports**:
   - 7860: Gradio interface
   - 6333: Qdrant database
   - Make sure these are available

## 🔧 Common Tasks

### Development Mode
```bash
# Start with logs visible
docker-compose up

# Code changes auto-reload (volumes mounted)
# Edit files on your Mac, changes reflect immediately
```

### Production Deploy
```bash
# Use production config
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Or build and push to registry
docker build -t genesis:latest .
docker tag genesis:latest your-registry/genesis:latest
docker push your-registry/genesis:latest
```

### Backup Data
```bash
# SQLite database
docker-compose exec genesis cp /app/data/conversations.db /app/data/backup.db

# Vector database (automatic with volumes)
docker run --rm -v genesis_qdrant-storage:/data -v $(pwd):/backup ubuntu tar czf /backup/qdrant-backup.tar.gz /data
```

## 🆘 Troubleshooting

**Services won't start?**
```bash
docker-compose logs genesis
docker-compose ps
```

**Can't connect to Ollama on Mac?**
- Use `http://host.docker.internal:11434` in .env
- Verify Ollama is running: `curl http://localhost:11434/api/tags`

**Permission issues?**
```bash
sudo chown -R $USER:$USER data/ logs/
```

**Port already in use?**
- Change ports in `docker-compose.yml`
- Or stop conflicting service: `lsof -i :7860`

## 📖 Full Documentation

See `docker/README.md` for:
- Complete command reference
- Advanced configuration
- Production deployment
- Monitoring and security
- Troubleshooting guide

## 🎉 You're All Set!

GENESIS will run with:
- ✅ Automatic startup
- ✅ Health monitoring
- ✅ Auto-restart on crash
- ✅ Persistent data
- ✅ Development hot-reload

**Next:** Customize your MISSION.md and start building! 🚀
