#!/bin/bash
set -e

# Initialize data directories for dual engines
mkdir -p /data/profiles/cloakbrowser
mkdir -p /data/profiles/camoufox
mkdir -p /data/kernels/camoufox

# Kill stale processes from previous container runs
pkill -f 'Xvnc :[0-9]' 2>/dev/null || true
pkill -f 'cloakbrowser.*chrome' 2>/dev/null || true
pkill -f 'chromium.*fingerprint' 2>/dev/null || true
pkill -f 'camoufox' 2>/dev/null || true
pkill -f xclip 2>/dev/null || true

# Clean Chrome lock files left on persistent volume (depth 3 for profiles/{engine}/{id})
find /data/profiles -maxdepth 3 -name 'SingletonLock' -delete 2>/dev/null || true
find /data/profiles -maxdepth 3 -name 'SingletonCookie' -delete 2>/dev/null || true
find /data/profiles -maxdepth 3 -name 'SingletonSocket' -delete 2>/dev/null || true

# Clean Firefox / Camoufox lock files
find /data/profiles -maxdepth 3 -name 'parent.lock' -delete 2>/dev/null || true
find /data/profiles -maxdepth 3 -name '.parentlock' -delete 2>/dev/null || true

# Remove X11 lock files from previous displays
rm -f /tmp/.X1*-lock 2>/dev/null || true

# Start FastAPI (serves built React + API)
cd /app
echo ""
echo "  AntiBrowser-Manager running at http://localhost:8080"
echo ""
exec uvicorn backend.main:app --host 0.0.0.0 --port 8080 --log-level warning
