#!/bin/zsh
# 一键启动网页版：首次会自动创建虚拟环境并安装 Streamlit
cd "$(dirname "$0")"
if [ ! -x .venv/bin/streamlit ]; then
  echo "正在准备网页版运行环境（首次约 1-2 分钟，使用国内镜像）…"
  python3 -m venv --clear .venv
  .venv/bin/pip install -q --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ --default-timeout=120
  .venv/bin/pip install -q -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --default-timeout=120
fi
set -a
source ./.env 2>/dev/null
set +a
.venv/bin/streamlit run app.py
