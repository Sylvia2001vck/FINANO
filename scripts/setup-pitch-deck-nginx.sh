#!/usr/bin/env bash
# One-time: expose pitch-deck on TCP 8082 (run on VPS with sudo).
set -euo pipefail

CONF_NAME="finano-pitch"
CONF_PATH="/etc/nginx/sites-available/${CONF_NAME}"
ENABLED="/etc/nginx/sites-enabled/${CONF_NAME}"

sudo tee "$CONF_PATH" > /dev/null <<'EOF'
server {
    listen 8082;
    listen [::]:8082;
    server_name _;

    root /var/www/finano-pitch-ppt;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* \.(mp4|mp3|png|jpg|jpeg|gif|webp|css|js|svg|ico)$ {
        expires 7d;
        add_header Cache-Control "public";
        try_files $uri =404;
    }
}
EOF

sudo ln -sf "$CONF_PATH" "$ENABLED"
sudo nginx -t
sudo systemctl reload nginx
echo "OK: pitch deck → http://<your-ip>:8082/ (open TCP 8082 in security group)"
