#!/bin/bash
# Pixiv Skill Packaging Script

SKILL_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$SKILL_DIR"

echo "📦 Cleaning up old packages..."
rm -f *.tgz

echo "🔍 Validating package.json..."
if [ ! -f "package.json" ]; then
    echo "❌ Error: package.json not found!"
    exit 1
fi

echo "🏗️ Building package..."
# 使用 npm pack 依照 package.json 定義打包
# 它會排除 node_modules 和 .gitignore 中的內容
PACKAGE_FILE=$(npm pack 2>/dev/null | tail -n 1)

if [ -f "$PACKAGE_FILE" ]; then
    echo "✅ Successfully packed: $PACKAGE_FILE"
else
    echo "❌ Failed to pack."
    exit 1
fi
