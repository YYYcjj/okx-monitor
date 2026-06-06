#!/bin/bash
# OKX 模拟合约交易 - 启动脚本
DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$DIR/.env" ]; then
    echo "⚠️  未找到 .env 配置文件"
    echo "   请复制 .env.example 为 .env 并填入你的 OKX 模拟交易 API 密钥"
    echo ""
    echo "   cp $DIR/.env.example $DIR/.env"
    exit 1
fi

set -a; source "$DIR/.env"; set +a

cd "$DIR/backend"
"$DIR/backend/venv/bin/python" server.py
