#!/bin/bash
set -eu
export DEBIAN_FRONTEND=noninteractive

stamp=$(date +%Y%m%d%H%M%S)
cp -a /etc/nginx "/etc/nginx.dsh-backup-${stamp}" 2>/dev/null || true
apt-get update -y
apt-get install -y nginx curl openssl

install -d -m 700 /etc/nginx/tls
if [ ! -s /etc/nginx/tls/server.crt ] || [ ! -s /etc/nginx/tls/server.key ]; then
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -keyout /etc/nginx/tls/server.key \
        -out /etc/nginx/tls/server.crt \
        -subj '/CN=dsh-workspace' \
        -addext 'subjectAltName=DNS:dsh-workspace,IP:127.0.0.1'
    chmod 600 /etc/nginx/tls/server.key
fi

cat >/etc/nginx/sites-available/dsh-proxy <<'NGINX'
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/tls/server.crt;
    ssl_certificate_key /etc/nginx/tls/server.key;

    if ($http_x_maastaatu_proxy_key != '{{tat-hidden:proxy_key}}') {
        return 401;
    }

    location / {
        proxy_pass http://127.0.0.1:3080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-MaaSTaaTu-Proxy-Key "";
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
NGINX

rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/dsh-proxy /etc/nginx/sites-enabled/dsh-proxy
nginx -t
systemctl enable --now nginx
curl --fail --max-time 10 --silent --show-error -k \
  -H 'X-MaaSTaaTu-Proxy-Key: {{tat-hidden:proxy_key}}' \
  -o /dev/null -w 'proxy_https_code=%{http_code}\n' https://127.0.0.1/
if curl --fail --max-time 5 --silent --output /dev/null -k https://127.0.0.1/; then
    echo 'Unexpected unauthenticated HTTPS success'
    exit 1
fi
ss -ltn 2>/dev/null | grep -E '(:443[[:space:]]|:443$)'
