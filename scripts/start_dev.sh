#!/bin/bash
# scripts/start_dev.sh - Development startup script

set -e

echo "🚀 Starting Design Research Agent v1.2 - Phase 1.1 Development"
echo "============================================================="

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: Please run this script from the design_research_agent directory"
    exit 1
fi

# Start PostgreSQL database
echo "📚 Starting PostgreSQL database..."
docker-compose -f docker-compose.dev.yml up -d postgres

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
timeout=30
counter=0
while ! docker-compose -f docker-compose.dev.yml exec -T postgres pg_isready -U postgres > /dev/null 2>&1; do
    counter=$((counter + 1))
    if [ $counter -gt $timeout ]; then
        echo "❌ Database failed to start within ${timeout} seconds"
        exit 1
    fi
    echo "   ... waiting (${counter}/${timeout})"
    sleep 1
done

echo "✅ Database ready!"

# Setup database schema
echo "🗃️  Setting up database schema..."
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/design_agent"
python3 scripts/setup_database.py

# Check if virtual environment exists and dependencies are installed
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

echo "📦 Activating virtual environment and installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

echo ""
echo "🎉 Development environment ready!"
echo ""
echo "🚀 To start the API server:"
echo "   source venv/bin/activate"
echo "   python3 main.py"
echo ""
echo "🔗 API will be available at:"
echo "   http://localhost:8000"
echo "   http://localhost:8000/docs (OpenAPI documentation)"
echo ""
echo "🗄️  Database connection:"
echo "   Host: localhost:5432"
echo "   Database: design_agent"
echo "   User: postgres"
echo "   Password: postgres"
echo ""
echo "🛑 To stop the database:"
echo "   docker-compose -f docker-compose.dev.yml down"