sudo mkdir -p /opt/ollama

if command -v zstd >/dev/null 2>&1; then
  curl -fL https://ollama.com/download/ollama-linux-arm64.tar.zst \
    | zstd -d \
    | sudo tar -xf - -C /opt/ollama
else
  curl -fL https://ollama.com/download/ollama-linux-arm64.tgz \
    | sudo tar -xzf - -C /opt/ollama
fi

sudo ln -sf /opt/ollama/bin/ollama /usr/local/bin/ollama

sudo useradd --system --create-home --home-dir /var/lib/ollama \
  --shell /usr/sbin/nologin ollama || true

sudo install -d -o ollama -g ollama /var/lib/ollama

sudo tee /etc/systemd/system/ollama.service > /dev/null <<'EOF'
[Unit]
Description=Ollama Service
After=network-online.target
Wants=network-online.target

[Service]
User=ollama
Group=ollama
WorkingDirectory=/var/lib/ollama
Environment=HOME=/var/lib/ollama
Environment=OLLAMA_HOST=0.0.0.0:11434
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ollama
systemctl status ollama --no-pager
curl -s http://127.0.0.1:11434/api/version
