
curl -s http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5:0.5b-nb",
    "stream": false,
    "messages": [
      {"role": "user", "content": "Reply with exactly OLLAMA_OK and nothing else."}
    ]
  }'
