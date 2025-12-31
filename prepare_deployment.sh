#!/bin/bash
# Deployment Preparation Script for cramzz.space
# Run this before deploying to production

echo "=========================================="
echo "🚀 Deployment Preparation for cramzz.space"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env exists
if [ -f ".env" ]; then
    echo -e "${GREEN}✅${NC} .env file exists"
    echo -e "${YELLOW}⚠️${NC}  Checking if it's configured for production..."
    
    if grep -q "FLASK_ENV=production" .env; then
        echo -e "${GREEN}✅${NC} FLASK_ENV=production is set"
    else
        echo -e "${RED}❌${NC} FLASK_ENV is not set to production"
        echo "   Add: FLASK_ENV=production to your .env file"
    fi
    
    if grep -q "PUBLIC_URL=https://cramzz.space" .env; then
        echo -e "${GREEN}✅${NC} PUBLIC_URL is set to https://cramzz.space"
    else
        echo -e "${YELLOW}⚠️${NC}  PUBLIC_URL is not set or incorrect"
        echo "   Add: PUBLIC_URL=https://cramzz.space to your .env file"
    fi
else
    echo -e "${YELLOW}⚠️${NC}  .env file not found"
    echo "   Copy production.env.template to .env and fill in values"
fi

echo ""
echo "=========================================="
echo "📋 Running Configuration Check..."
echo "=========================================="
echo ""

# Run the config checker
if [ -f "check_production_config.py" ]; then
    python3 check_production_config.py
else
    echo -e "${RED}❌${NC} check_production_config.py not found"
fi

echo ""
echo "=========================================="
echo "📦 Checking Git Status..."
echo "=========================================="
echo ""

# Check if git is initialized
if [ -d ".git" ]; then
    echo -e "${GREEN}✅${NC} Git repository initialized"
    
    # Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        echo -e "${YELLOW}⚠️${NC}  You have uncommitted changes:"
        git status --short
        echo ""
        echo "Commit changes before deploying:"
        echo "  git add ."
        echo "  git commit -m 'Production config for cramzz.space'"
        echo "  git push origin main"
    else
        echo -e "${GREEN}✅${NC} No uncommitted changes"
        echo ""
        echo "Ready to deploy! Push to GitHub:"
        echo "  git push origin main"
    fi
else
    echo -e "${RED}❌${NC} Git repository not initialized"
    echo "Initialize git and push to GitHub:"
    echo "  git init"
    echo "  git add ."
    echo "  git commit -m 'Initial commit'"
    echo "  git remote add origin <your-repo-url>"
    echo "  git push -u origin main"
fi

echo ""
echo "=========================================="
echo "🔒 Security Check..."
echo "=========================================="
echo ""

# Check if sensitive files are ignored
if grep -q "\.env" .gitignore && grep -q "tokens\.db" .gitignore; then
    echo -e "${GREEN}✅${NC} Sensitive files are in .gitignore"
else
    echo -e "${RED}❌${NC} Some sensitive files might not be ignored"
    echo "   Verify .gitignore contains: .env, tokens.db, *.db"
fi

# Check if .env is in git history
if [ -d ".git" ]; then
    if git log --all --full-history -- .env > /dev/null 2>&1; then
        echo -e "${RED}❌${NC} WARNING: .env might be in git history!"
        echo "   This is a security risk. Consider:"
        echo "   - Remove .env from git history"
        echo "   - Rotate all secrets (generate new SECRET_KEY, CLIENT_SECRET)"
    else
        echo -e "${GREEN}✅${NC} .env is not in git history"
    fi
fi

echo ""
echo "=========================================="
echo "📝 Next Steps:"
echo "=========================================="
echo ""
echo "1. Update Spotify Developer Dashboard:"
echo "   → Add redirect URI: https://cramzz.space/redirect"
echo ""
echo "2. Choose hosting platform:"
echo "   → Render.com (recommended)"
echo "   → Railway.app"
echo "   → Your own VPS"
echo ""
echo "3. Set environment variables on hosting platform"
echo ""
echo "4. Configure DNS for cramzz.space"
echo ""
echo "5. Deploy and test!"
echo ""
echo "📚 Read the guides:"
echo "   • DEPLOY_TO_CRAMZZ.md - Complete deployment guide"
echo "   • DEPLOYMENT_CHECKLIST.md - Step-by-step checklist"
echo ""
echo "=========================================="

