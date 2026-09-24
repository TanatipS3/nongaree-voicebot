#!/bin/zsh
cd /Users/max/Documents/RD/nongaree-voicebot || exit 1

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found on PATH."
  echo "Install Node.js first, then rerun this file."
  echo
  echo "After Node is installed, this command will start the existing demo:"
  echo "  npm install"
  echo "  npm run dev"
  echo
  echo "Press any key to close this terminal."
  read -k 1
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "Installing frontend dependencies..."
  npm install || exit 1
fi

echo "Starting Nongaree frontend demo..."
echo "Open http://localhost:3000 if the browser does not open automatically."
(sleep 3 && open http://localhost:3000) &
npm run dev
