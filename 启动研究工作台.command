#!/bin/bash
set -u
cd -- "$(dirname -- "$0")" || exit 2
python3 scripts/launch_workspace.py
result=$?
if [ "$result" -ne 0 ]; then
  read -r -p '按回车关闭窗口…'
fi
exit "$result"
