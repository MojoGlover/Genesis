#!/bin/bash
set -e

echo "🚀 Setting up GENESIS..."

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --break-system-packages

# Create directories
echo "📁 Creating directories..."
mkdir -p data/uploads data/cache

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "🔑 Creating .env file..."
    cat > .env << 'ENVEOF'
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
GOOGLE_API_KEY=your_key_here
DATABASE_URL=sqlite:///./data/memory.db
QDRANT_URL=http://localhost:6333
ENVEOF
    echo "⚠️  Edit .env and add your API keys"
fi

# Create mission file from example
if [ ! -f MISSION.md ]; then
    echo "📋 Creating MISSION.md from template..."
    cp MISSION.md.example MISSION.md
    echo "⚠️  Edit MISSION.md to define your AI's purpose"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit MISSION.md (define your AI's purpose)"
echo "2. Edit .env (add API keys if using cloud providers)"
echo "3. Run: uvicorn app:app --reload"
echo "4. Run: python3 interface.py"
