#!/usr/bin/env bash
# Finish arescope.com: issue a Let's Encrypt cert and switch the vhost to HTTPS.
#
# Run ONCE arescope.com + www resolve to this server (159.195.194.172 / IPv6) and
# the bootstrap vhost (deploy/nginx/arescope.conf) + static container
# (deploy/docker-compose.web.yml) are already up. Validates nginx before reloading,
# so it won't take down the other sites (insureares, aresium, arestoteles,
# ares-empire) on the shared gateway.
#
#   sudo bash deploy/enable-tls-arescope.sh
set -euo pipefail

DOMAIN=arescope.com
WWW=www.arescope.com
EMAIL=breeckpatrik@gmail.com
PORT=5190
CONF=/root/insureai/InsureAI/backend/nginx/conf.d/arescope.conf
CERTBOT_CONF=/root/insureai/InsureAI/backend/certbot/conf
CERTBOT_WWW=/root/insureai/InsureAI/backend/certbot/www

echo "==> Checking DNS resolves to this host..."
for d in "$DOMAIN" "$WWW"; do
  ip=$(getent hosts "$d" | awk '{print $1}' | head -1 || true)
  echo "    $d -> ${ip:-<unresolved>}"
  [ -z "$ip" ] && { echo "!! $d does not resolve yet. Wait for DNS, then re-run." >&2; exit 1; }
done

echo "==> Requesting cert via webroot (HTTP-01)..."
docker run --rm \
  -v "$CERTBOT_CONF":/etc/letsencrypt \
  -v "$CERTBOT_WWW":/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d "$DOMAIN" -d "$WWW" \
  --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo "==> Writing HTTPS vhost..."
cat > "$CONF" <<NGINX
# ============================================================
# Arescope — arescope.com (HTTPS). Additive vhost on insureai_nginx.
# Proxies to the static site container on the bridge gateway 172.18.0.1:$PORT
# (deploy/docker-compose.web.yml). Static marketing site, no app/auth.
# ============================================================

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN $WWW;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name $DOMAIN $WWW;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL_arescope:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # canonicalize www -> apex
    if (\$host = www.$DOMAIN) { return 301 https://$DOMAIN\$request_uri; }

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    gzip on;
    gzip_proxied any;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml application/font-woff2 font/woff2;
    gzip_min_length 1024;

    client_max_body_size 1M;

    # long-cache fingerprinted assets (Astro emits hashed filenames under /_astro/)
    location /_astro/ {
        proxy_pass http://172.18.0.1:$PORT;
        proxy_set_header Host \$host;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://172.18.0.1:$PORT;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_connect_timeout 10s;
        proxy_read_timeout    30s;
        proxy_send_timeout    30s;
    }
}
NGINX

echo "==> Validating + reloading nginx..."
docker exec insureai_nginx nginx -t
docker exec insureai_nginx nginx -s reload
echo "==> Done. https://$DOMAIN should now be live."
