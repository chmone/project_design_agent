#!/bin/bash
# scripts/setup_local_dev.sh - Local development without Docker

set -e

echo "🚀 Setting up Design Research Agent v1.2 - Local Development"
echo "============================================================="

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: Please run this script from the design_research_agent directory"
    exit 1
fi

echo "📋 This script will help you set up local development without Docker"
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "🐍 Python version: $python_version"

if [[ "$python_version" < "3.11" ]]; then
    echo "⚠️  Warning: Python 3.11+ recommended, you have $python_version"
else
    echo "✅ Python version compatible"
fi

# Check PostgreSQL
echo ""
echo "🗄️  Checking PostgreSQL installation..."
if command -v psql >/dev/null 2>&1; then
    psql_version=$(psql --version | head -n1)
    echo "✅ PostgreSQL found: $psql_version"
    echo ""
    echo "📝 Please ensure PostgreSQL is running and create the database:"
    echo "   createdb design_agent"
    echo "   # OR using psql:"
    echo "   psql -c 'CREATE DATABASE design_agent;'"
else
    echo "❌ PostgreSQL not found. Please install PostgreSQL:"
    echo ""
    echo "   Ubuntu/Debian: sudo apt-get install postgresql postgresql-contrib"
    echo "   macOS: brew install postgresql"
    echo "   Or use Docker: docker run --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:15"
fi

# Create virtual environment
echo ""
echo "📦 Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists" 
fi

# Activate and install dependencies
echo ""
echo "📦 Installing dependencies..."
source venv/bin/activate

# Create a minimal requirements file for testing
cat > requirements.minimal.txt << EOF
# Minimal requirements for testing Phase 1.1
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
asyncpg>=0.29.0
structlog>=23.2.0
python-dotenv>=1.0.0
pytest>=7.4.3
pytest-asyncio>=0.21.1
EOF

pip install -r requirements.minimal.txt

echo ""
echo "🎉 Local development environment setup complete!"
echo ""
echo "📋 Next steps:"
echo ""
echo "1. 🗄️  Start PostgreSQL and create database:"
echo "   createdb design_agent"
echo ""
echo "2. 🗃️  Set up database schema:"
echo "   export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/design_agent'"
echo "   source venv/bin/activate"
echo "   python3 scripts/setup_database.py"
echo ""
echo "3. 🚀 Start the API server:"
echo "   source venv/bin/activate"
echo "   python3 main.py"
echo ""
echo "4. 🧪 Run tests:"
echo "   source venv/bin/activate"
echo "   python3 -m pytest tests/ -v"
echo ""
echo "🔗 API will be available at:"
echo "   http://localhost:8000"
echo "   http://localhost:8000/docs (OpenAPI documentation)"
echo ""
echo "💡 If you don't have PostgreSQL, you can use Docker for just the database:"
echo "   docker run --name design-agent-postgres \\"
echo "     -e POSTGRES_DB=design_agent \\"
echo "     -e POSTGRES_USER=postgres \\"
echo "     -e POSTGRES_PASSWORD=postgres \\"
echo "     -p 5432:5432 -d postgres:15"