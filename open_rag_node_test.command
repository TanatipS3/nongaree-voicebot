#!/bin/zsh
cd /Users/max/Documents/RD/nongaree-voicebot || exit 1

echo "Testing Nongaree retrieve node..."
echo
python3 rag_node_test.py "${1:-เงินเดือนเท่าไหร่ถึงต้องเสียภาษี?}"

echo
echo "Done. Press any key to close this terminal."
read -k 1
