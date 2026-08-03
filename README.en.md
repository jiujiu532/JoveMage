<p align="center">
  <img src="web-vue/public/logo.svg?v=0.8.1" width="96" alt="JoveMage logo">
</p>

<h1 align="center">JoveMage</h1>

<p align="center">
  Multi-channel self-hosted console: ChatGPT web + Adobe Firefly as OpenAI / Anthropic compatible APIs
</p>

<p align="center">
  <a href="https://github.com/jiujiu532/JoveMage/stargazers"><img src="https://img.shields.io/github/stars/jiujiu532/JoveMage?style=flat-square&logo=github" alt="GitHub stars"></a>
  <a href="VERSION"><img src="https://img.shields.io/badge/version-v0.8.1-2563eb?style=flat-square" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-f97316?style=flat-square" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-≥3.13-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.136-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://vuejs.org/"><img src="https://img.shields.io/badge/Vue-3.5-42b883?style=flat-square&logo=vuedotjs&logoColor=white" alt="Vue"></a>
  <a href="https://github.com/jiujiu532/JoveMage/pkgs/container/jovemage"><img src="https://img.shields.io/badge/GHCR-jiujiu532%2Fjovemage-black?style=flat-square&logo=docker&logoColor=white" alt="GHCR"></a>
</p>

<p align="center">
  <a href="README.md">中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="https://github.com/jiujiu532/JoveMage/releases">Releases</a> ·
  <a href="docs/deployment.md">Deploy docs</a>
</p>

---

JoveMage is a **multi-channel AI gateway + ops console** for self-hosters:

- **ChatGPT channel**: reverse-engineers chatgpt.com for chat, search, image generate/edit — OpenAI / Anthropic compatible
- **Adobe Firefly channel**: Express Cookie pools; image / image-to-image / video (e.g. Sora family) on the same `/v1` surface
- **Unified pool & governance**: per-channel routing, dual meters (quota + credits), reconcile, usage profiles, request traces
- **Vue console**: dashboard, accounts, logs, gallery, monitor, register, settings, Studio

One FastAPI process serves both API and console.

> **Image**: `ghcr.io/jiujiu532/jovemage`  
> **Version**: `v0.8.1`  
> **Env compatibility**: `CHATGPT2API_*` variables still work

## Features

- **API compatibility**: `/v1/chat/completions`, `/v1/messages`, `/v1/images/*`, `/v1/videos/generations`, `/v1/models`, …
- **Channel registry**: ChatGPT + Firefly as first-class channels; capabilities (`chat` / `image` / `edit` / `video`) drive Studio & UI
- **Account pool**: freshness metrics, round-robin, token refresh / failover; Firefly identity dedupe by `account_id` and cookie→IMS exchange
- **Bulk account tasks**: refresh / inspect / delete / relogin / enable-disable-reset as unified backend jobs; light·heavy tier locks, stop at batch boundary, dual top-bar progress strips with resume after reload
- **Registration** (ChatGPT): passwordless signup, many mail providers, proxy pool binding
- **Image / video pipelines**: generate · edit · video task polling, storage, structured failure accounting
- **Anti-ban proxies**: WARP 1–6 instances, `proxy_pool`, optional FlareSolverr
- **Vue console**: channel-aware dashboard / accounts / logs / gallery / monitor / register / settings / Studio
- **Pluggable storage**: `json` / `sqlite` / `postgres` / `git` for accounts & auth keys

## Quick start

### Installer (recommended)

```bash
bash <(curl -sL https://raw.githubusercontent.com/jiujiu532/JoveMage/main/install.sh)
```

Or:

```bash
git clone https://github.com/jiujiu532/JoveMage.git
cd JoveMage
bash install.sh
```

The installer covers install, status, config, image updates, image cleanup, uninstall, and IP rotation.

### Docker Compose

```bash
mkdir -p /opt/jovemage/data && cd /opt/jovemage

cat > config.json << 'EOF'
{
  "auth-key": "replace-with-a-strong-secret",
  "proxy": "",
  "proxy_pool": [],
  "max_relogin_retries": 3,
  "refresh_account_interval_minute": 15,
  "image_retention_days": 15,
  "image_max_retries": 3,
  "auto_remove_invalid_accounts": true
}
EOF

cat > docker-compose.yml << 'EOF'
services:
  app:
    image: ghcr.io/jiujiu532/jovemage:latest
    container_name: jovemage
    restart: unless-stopped
    ports:
      - "127.0.0.1:9000:80"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json
    environment:
      - TZ=Asia/Shanghai
    networks:
      - jovemage_net

networks:
  jovemage_net:
    name: jovemage_net
EOF

docker compose up -d
```

> If the GHCR package is private:  
> `echo <PAT> | docker login ghcr.io -u <username> --password-stdin`

### Local development

```bash
export CHATGPT2API_AUTH_KEY=local-dev-key
uv sync
uv run python main.py
# default http://127.0.0.1:8000

cd web-vue
npm install
npm run dev
# Vite proxies API to localhost:8000
```

## Endpoints

| Item | URL |
|------|-----|
| Console | `http://127.0.0.1:9000` (compose default; change as needed) |
| API | `http://127.0.0.1:9000/v1` |
| Data | `/opt/jovemage/data/` |

Login password = `auth-key` in `config.json` (or `CHATGPT2API_AUTH_KEY`).

## Configuration (high level)

| Key | Purpose | Default |
|-----|---------|---------|
| `auth-key` | Console + API secret | **required** (process refuses to start if missing) |
| `proxy` | Default egress proxy | empty |
| `proxy_pool` | Registration proxy pool | `[]` |
| `max_relogin_retries` | Relogin retries `0–10` | `3` |
| `refresh_account_interval_minute` | Freshness window (min) | `15` |
| `image_retention_days` | Image retention | `15` |
| `image_max_retries` | Image failover retries | `3` |
| `auto_remove_invalid_accounts` | Drop auth-invalid accounts | `true` |
| `firefly_enabled` | Enable Adobe Firefly channel | `false` |
| `firefly_video_enabled` | Enable Firefly video capability | `false` |

Full reference: `config.example.yaml`. Firefly needs Express Cookie accounts imported in the console (Settings → Firefly).

## Upgrade

```bash
bash install.sh   # menu: Update image
# or
cd /opt/jovemage && docker compose pull && docker compose up -d
```

## CI / Image

- On push to `main` or tags `v*`, GitHub Actions builds multi-arch images to GHCR
- Image: `ghcr.io/jiujiu532/jovemage` (`linux/amd64` + `linux/arm64`)
- Tags: `latest` (main), `v0.8.1`, `0.8`, `sha-...`
- Workflow: `.github/workflows/docker-publish.yml`

## Disclaimer

This project reverse-engineers ChatGPT web and Adobe Firefly / Express related surfaces for **personal learning and non-commercial research only**. Do not use it for commercial abuse, bulk automation that violates OpenAI / Adobe ToS, or illegal content. You assume all risks including account bans and legal liability.

---

<p align="center">MIT · Made for self-hosters</p>
