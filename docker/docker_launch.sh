#!/bin/bash

if [ -z "$OPENAI_API_KEY" ]; then
  echo "Error: OPENAI_API_KEY is not set."
  echo "Please set the OPENAI_API_KEY environment variable using the command:"
  echo "docker run -e OPENAI_API_KEY='your-api-key'."
  exit 1
fi

export PYTHONPATH=/PPTAgent/src:$PYTHONPATH

# Launch Backend Server
cd /PPTAgent
python3 pptagent_ui/backend.py &

# Launch Frontend Server
cd pptagent_ui
npm install
npm run serve
