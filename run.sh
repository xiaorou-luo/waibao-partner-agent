#!/bin/zsh
# 一键启动外脑伙伴：读取 .env 里的密钥，然后进入交互对话
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "缺少 .env 配置文件。请先创建 .env，内容："
  echo "  LLM_PROVIDER=deepseek"
  echo "  LLM_API_KEY=你的密钥"
  exit 1
fi
set -a
source ./.env
set +a
python3 chat.py
