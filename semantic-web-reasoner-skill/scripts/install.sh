#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_DIR="/home/chimezie/.opencode/tools"

echo "=== Building TypeScript plugin ==="
cd "$REPO_DIR"
npm run build

echo "=== Deploying Python backend scripts to $TOOLS_DIR ==="
mkdir -p "$TOOLS_DIR"
for py in "$REPO_DIR/skills/semantic-web-reasoner-skill/scripts/"*.py; do
  cp "$py" "$TOOLS_DIR/"
done

echo "=== Deploying standalone .ts tool definitions ==="
cp "$REPO_DIR"/src/*.ts "$TOOLS_DIR/"

echo "=== Deploy complete ==="
echo "Python scripts deployed:"
ls -la "$TOOLS_DIR/"*.py
echo "TypeScript tool definitions:"
ls -la "$TOOLS_DIR/"*.ts
