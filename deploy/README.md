# Deploying the Aresis site (arescope.com)

The marketing site is a **static** Astro build (`web/dist`) served by a small
dedicated nginx, reverse-proxied by the shared `insureai_nginx` gateway — the
same additive pattern as `aresium` and `ares-empire`. Nothing here touches the
other vhosts or the shared compose.

**Target server:** `159.195.194.172` (the consolidated gateway — confirmed: it's
where `insureares.de`, `aresium.de`, `ares-empire.de` and now `arescope.com` all
resolve). DNS for `arescope.com` + `www` is already live.

## Pre-flight (once)

Confirm the docker bridge gateway IP the shared nginx reaches host services on:

```bash
docker network inspect insureai_network -f '{{(index .IPAM.Config 0).Gateway}}'
```

If it isn't `172.18.0.1`, change the published IP in `docker-compose.web.yml` and
the `proxy_pass` / `PORT` in `nginx/arescope.conf` + `enable-tls-arescope.sh`.
Also confirm port `5190` is free (`ss -ltnp | grep 5190`); pick another if not.

## Steps (run on the server, in the repo root)

```bash
# 1. Build the static site (needs Node >=20.3; or build elsewhere and copy web/dist over)
cd web && npm ci && npm run build && cd ..

# 2. Bring up the static container on 172.18.0.1:5190
docker compose -f deploy/docker-compose.web.yml up -d
curl -sI http://172.18.0.1:5190 | head -1     # expect: HTTP/1.1 200 OK

# 3. Install the HTTP bootstrap vhost into the shared gateway, validate, reload
cp deploy/nginx/arescope.conf /root/insureai/InsureAI/backend/nginx/conf.d/
docker exec insureai_nginx nginx -t
docker exec insureai_nginx nginx -s reload
curl -sI http://arescope.com | head -1        # expect: 200 (served over HTTP)

# 4. Issue the Let's Encrypt cert and flip the vhost to HTTPS
sudo bash deploy/enable-tls-arescope.sh
```

Then verify `https://arescope.com` (and that `www` + `http` redirect to it).

## Updating the site later

```bash
cd web && npm ci && npm run build && cd ..
docker compose -f deploy/docker-compose.web.yml restart web   # picks up new dist
```

(The `web/dist` is bind-mounted read-only, so a rebuild + container restart is all
it takes. No cert or vhost changes needed.)

## Notes

- The cert auto-renews via the existing certbot daemon on the shared stack (the
  HTTPS vhost serves `/.well-known/acme-challenge/` from the shared `certbot/www`).
- Rollback: `rm` the conf from `conf.d/`, `nginx -t && nginx -s reload`,
  `docker compose -f deploy/docker-compose.web.yml down`. The other sites are
  unaffected at every step.
</content>
