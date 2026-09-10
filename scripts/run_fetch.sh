#!/bin/bash
# run_fetch.sh — 被 launchd 调用的 wrapper
# 从 .env 读 key，避免 key 写进 plist

set -e
cd "$(dirname "$0")/.."

# 优先 .env，其次 ~/.zshenv / ~/.bashrc
if [ -f .env ]; then
  set -a; . ./.env; set +a
elif [ -f ~/.zshenv ]; then
  source ~/.zshenv
elif [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

if [ -z "$MINIMAX_API_KEY" ]; then
  echo "[$(date)] MINIMAX_API_KEY 未设置" >> /tmp/literature-tracker-fetch.log
  exit 1
fi

/usr/bin/python3 -u scripts/fetch_rss.py >> /tmp/literature-tracker-fetch.log 2>&1
echo "[$(date)] 完成 exit=$?" >> /tmp/literature-tracker-fetch.log
