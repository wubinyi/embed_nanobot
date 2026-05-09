sudo -u ollama -H HOME=/var/lib/ollama /usr/local/bin/ollama pull qwen2.5:0.5b

cat > /tmp/Modelfile.qwen2.5-0.5b-nb <<'EOF'
FROM qwen2.5:0.5b
PARAMETER num_ctx 8192
EOF

sudo -u ollama -H HOME=/var/lib/ollama /usr/local/bin/ollama create \
  qwen2.5:0.5b-nb -f /tmp/Modelfile.qwen2.5-0.5b-nb

sudo -u ollama -H HOME=/var/lib/ollama /usr/local/bin/ollama list
