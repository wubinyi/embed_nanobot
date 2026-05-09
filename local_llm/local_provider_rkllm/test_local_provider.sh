# curl -s http://127.0.0.1:18000/v1/chat/completions \
#   -H 'Content-Type: application/json' \
#   -d '{
#     "model":"qwen3-vl-2b-rkllm",
#     "stream":false,
#     "messages":[
#       {"role":"system","content":"Reply with exactly RKLLM_OK and nothing else."},
#       {"role":"user","content":"Reply with exactly RKLLM_OK and nothing else."}
#     ]
#   }'

curl -s http://127.0.0.1:18000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"qwen3-vl-2b-rkllm",
    "stream":false,
    "messages":[
      {"role":"system","content":"You are a helpful assistant for testing RKLLM and nanobot"},
      {"role":"user","content":"Hello"}
    ]
  }'