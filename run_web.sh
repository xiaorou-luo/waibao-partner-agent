#!/bin/zsh
# 一键启动网页版：首次会自动创建虚拟环境并安装 Streamlit
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "首次运行，正在创建虚拟环境并安装 Streamlit（可能需要一两分钟）…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
set -a
source ./.env 2>/dev/null
set +a
.venv/bin/streamlit run app.py
