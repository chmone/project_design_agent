# Troubleshooting Guide - Design Research Agent v1.2

## 🐛 Common Issues and Solutions

### Docker Compose Hanging/Timeout

**Problem**: `docker-compose up -d` hangs or times out without completing.

**Symptoms**:
- Command doesn't return to prompt
- Warning about obsolete `version` attribute
- Timeout errors after 2+ minutes

**Solutions**:

#### Option 1: Restart Docker Daemon
```bash
# Check Docker daemon status
sudo systemctl status docker

# Restart Docker daemon
sudo systemctl restart docker

# Try again
docker-compose -f docker-compose.dev.yml up -d
```

#### Option 2: Use Local Development Setup (Recommended)
```bash
# Use the local development script instead
./scripts/setup_local_dev.sh

# Or manually:
# 1. Start PostgreSQL locally or with single Docker container
docker run --name design-agent-postgres \
  -e POSTGRES_DB=design_agent \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 -d postgres:15

# 2. Setup environment
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn asyncpg pydantic structlog

# 3. Setup database
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/design_agent"
python3 scripts/setup_database.py

# 4. Start API
python3 main.py
```

#### Option 3: Clean Docker Environment
```bash
# Stop all containers
docker stop $(docker ps -aq) 2>/dev/null || true

# Remove containers
docker rm $(docker ps -aq) 2>/dev/null || true

# Remove unused networks
docker network prune -f

# Try again with simplified compose
docker-compose -f docker-compose.dev.yml up -d
```

### Missing Dependencies

**Problem**: Import errors when running the application.

**Common Error**: `ModuleNotFoundError: No module named 'fastapi'`

**Solutions**:

#### Virtual Environment Path Issues (TESTED SOLUTION ✅)
```bash
# If modules exist but aren't found, set PYTHONPATH
export PYTHONPATH=/home/chmonesmith/Projects/design_agent/.venv/lib/python3.10/site-packages:$PYTHONPATH

# Test import
python3 -c "import fastapi; print('FastAPI found')"

# Run application with path
PYTHONPATH=/home/chmonesmith/Projects/design_agent/.venv/lib/python3.10/site-packages:$PYTHONPATH python3 design_research_agent/main.py
```

#### Install Dependencies
```bash
# Install minimal dependencies for testing
pip install fastapi uvicorn asyncpg pydantic structlog python-dotenv pytest pytest-asyncio

# Or install into user site-packages
python3 -m pip install --user asyncpg fastapi uvicorn
```

#### Apt Package Manager Lock Issues (RESOLVED ✅)
**Problem**: `Could not get lock /var/lib/apt/lists/lock`

**Solution**:
```bash
# Kill stuck apt processes
sudo kill -9 $(pgrep apt)
sudo killall -9 apt dpkg

# Clean locks
sudo rm -f /var/lib/apt/lists/lock
sudo rm -f /var/cache/apt/archives/lock
sudo rm -f /var/lib/dpkg/lock*

# Fix interrupted installations
sudo dpkg --configure -a

# Fresh update and install
sudo apt update
sudo apt install postgresql postgresql-contrib -y
```

### Database Connection Issues

**Problem**: Cannot connect to PostgreSQL database.

**Common Error**: `password authentication failed for user "postgres"`

**Solutions**:

#### Setup PostgreSQL User (TESTED SOLUTION ✅)
```bash
# Create PostgreSQL user matching system user
sudo -u postgres psql
CREATE USER chmonesmith SUPERUSER;
CREATE DATABASE design_agent OWNER chmonesmith;
\q

# Test connection with local socket (no password needed)
export DATABASE_URL='postgresql:///design_agent'
python3 -c "
import asyncpg
import asyncio

async def test():
    conn = await asyncpg.connect('postgresql:///design_agent')
    result = await conn.fetchval('SELECT 1')
    print(f'✅ Database connection successful: {result}')
    await conn.close()

asyncio.run(test())
"
```

#### Alternative: Password-based Connection
```bash
# If using password authentication
export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/design_agent'

# Test connection
psql -h localhost -U postgres -d design_agent -c "SELECT 1;"
```

### Port Already in Use

**Problem**: Port 5432 or 8000 already in use.

**Solutions**:
```bash
# Check what's using the port
sudo lsof -i :5432
sudo lsof -i :8000

# Kill process using port (if safe to do so)
sudo kill -9 $(lsof -t -i:5432)

# Or use different ports
export DATABASE_URL="postgresql://postgres:postgres@localhost:5433/design_agent"
export PORT=8001
python3 main.py
```

### Python Version Issues

**Problem**: Code doesn't work with older Python versions.

**Solutions**:
```bash
# Check Python version
python3 --version

# If < 3.10, install newer Python or use pyenv
# Ubuntu/Debian:
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev

# Create venv with specific version
python3.11 -m venv venv
source venv/bin/activate
```

## 🔧 Development Workflows

### Quick Start (No Docker)
```bash
# 1. Setup
git clone <repo>
cd design_research_agent
./scripts/setup_local_dev.sh

# 2. Start database (choose one)
# Option A: Local PostgreSQL
createdb design_agent

# Option B: Docker container
docker run --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:15

# 3. Initialize
source venv/bin/activate
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/design_agent"
python3 scripts/setup_database.py

# 4. Start API
python3 main.py
```

### Testing Workflow
```bash
# Unit tests (no database required)
python3 -c "
from domain.models.agent_context import AgentInput, AnalysisDepth
from datetime import datetime
print('✅ Basic model imports working')
"

# Database tests (requires running database)
python3 -c "
import asyncio
import asyncpg

async def test():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/design_agent')
    tables = await conn.fetch(\"SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'\")
    print(f'✅ Found {len(tables)} tables')
    await conn.close()

asyncio.run(test())
"

# API tests (requires running API)
curl http://localhost:8000/health
curl http://localhost:8000/
```

### Docker Troubleshooting
```bash
# Check Docker daemon
docker info

# Check compose file syntax
docker-compose -f docker-compose.dev.yml config

# View logs
docker-compose -f docker-compose.dev.yml logs postgres

# Clean restart
docker-compose -f docker-compose.dev.yml down -v
docker-compose -f docker-compose.dev.yml up -d
```

## 🚨 Emergency Fallback

If everything fails, you can still test the core functionality:

```bash
# 1. Test basic imports
python3 -c "
from domain.models.agent_context import *
from domain.models.task_state import *
print('✅ All models import successfully')
"

# 2. Test database schema (without connection)
python3 -c "
with open('scripts/setup_database.py', 'r') as f:
    content = f.read()
    table_count = content.count('CREATE TABLE')
    print(f'✅ Schema defines {table_count} tables')
"

# 3. Test API structure (without running)
python3 -c "
with open('main.py', 'r') as f:
    content = f.read()
    endpoint_count = content.count('@app.')
    print(f'✅ API defines {endpoint_count} endpoints')
"
```

## 📞 Getting Help

1. **Check logs**: Always check container logs for specific error messages
2. **Verify environment**: Ensure Python 3.10+, PostgreSQL available
3. **Use fallbacks**: Local development script works without Docker
4. **Test incrementally**: Start with database, then API, then full system

## ✅ Success Indicators

When everything is working correctly, you should see:

```bash
# Database running
$ docker ps
CONTAINER ID   IMAGE           STATUS
abc123def456   postgres:15     Up 2 minutes (healthy)

# API responding
$ curl http://localhost:8000/health
{"status":"healthy","database":"connected",...}

# No hanging commands
$ docker-compose -f docker-compose.dev.yml up -d
Creating design_agent_postgres_dev ... done
$ # Should return to prompt immediately
```