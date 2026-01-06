#!/bin/bash
# GENESIS Docker Quick Start Script

set -e  # Exit on error

echo "🚀 GENESIS Docker Setup"
echo "======================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose found"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "✅ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env and add your API keys!"
    echo "   Run: nano .env"
    echo ""
    read -p "Press Enter to continue after editing .env, or Ctrl+C to exit..."
else
    echo "✅ .env file already exists"
fi

# Check if MISSION.md exists
if [ ! -f MISSION.md ]; then
    echo "📝 Creating MISSION.md from example..."
    if [ -f MISSION.md.example ]; then
        cp MISSION.md.example MISSION.md
        echo "✅ MISSION.md created"
    else
        echo "⚠️  MISSION.md.example not found, skipping..."
    fi
fi

echo ""
echo "🏗️  Building and starting GENESIS..."
echo ""

# Build and start services
docker-compose up -d --build

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 5

# Check if services are running
if docker-compose ps | grep -q "Up"; then
    echo ""
    echo "✅ GENESIS is running!"
    echo ""
    echo "📊 Service Status:"
    docker-compose ps
    echo ""
    echo "🌐 Access Points:"
    echo "   Gradio Interface: http://localhost:7860"
    echo "   Qdrant Dashboard: http://localhost:6333/dashboard"
    echo ""
    echo "📋 Useful Commands:"
    echo "   View logs:        docker-compose logs -f"
    echo "   Stop services:    docker-compose down"
    echo "   Restart:          docker-compose restart"
    echo "   Shell access:     docker-compose exec genesis bash"
    echo ""
    echo "📖 Full docs: docker/README.md"
    echo ""
    
    # Offer to open browser
    if command -v open &> /dev/null; then
        read -p "Open Gradio interface in browser? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            open http://localhost:7860
        fi
    fi
else
    echo ""
    echo "⚠️  Services may not be fully started yet."
    echo "   Check status: docker-compose ps"
    echo "   View logs:    docker-compose logs"
fi
