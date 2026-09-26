#!/bin/bash
# Double-click this file to start the Diatom Analyzer.
# The first start sets everything up (a few minutes, needs internet once); later starts are quick.

cd "$(dirname "$0")" || exit 1
clear
echo "=================================================="
echo "  Diatom Analyzer"
echo "  Keep this window open while you use the tool."
echo "  To quit: close the browser tab, then this window."
echo "=================================================="
echo

problem() {  # a dialog box as well as text, since the terminal window is easy to overlook
  echo "$1"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 with title \"Diatom Analyzer\"" >/dev/null 2>&1
  fi
}

PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  problem "Python 3.10 or newer is needed (a one-time install). The download page will open: install Python, then double-click Start Diatom Analyzer again."
  if command -v open >/dev/null 2>&1; then open "https://www.python.org/downloads/"; fi
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "First start: setting things up. This takes a few minutes and needs internet once..."
  if ! "$PY" -m venv .venv; then
    problem "Setup failed while preparing Python. Please ask whoever looks after the tool."
    exit 1
  fi
fi

REQUIREMENTS_ID=$( (shasum requirements.txt 2>/dev/null || sha1sum requirements.txt) | cut -d' ' -f1)
if [ ! -f .venv/installed.txt ] || [ "$(cat .venv/installed.txt)" != "$REQUIREMENTS_ID" ]; then
  echo "Installing the analysis tools..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  if ! .venv/bin/python -m pip install --quiet -r requirements.txt; then
    problem "Installing the tools failed. Check the internet connection, then double-click Start Diatom Analyzer again."
    exit 1
  fi
  echo "$REQUIREMENTS_ID" > .venv/installed.txt
fi

# Streamlit asks for an email address on its very first run, which would stall here unseen.
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  mkdir -p "$HOME/.streamlit"
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo "Opening the Diatom Analyzer in your browser..."
exec .venv/bin/python -m streamlit run app.py --server.headless false
