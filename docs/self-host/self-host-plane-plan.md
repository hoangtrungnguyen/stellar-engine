# Self-Host Plane Plan

## Why Self-Host

Plane Cloud does not yet expose `PATCH /api/v1/.../pages/{id}/` for project pages.
The `preview` branch (PR #9020) already implements full CRUD for pages — available only on self-hosted.

## VPS Requirements

| | Minimum | Recommended |
|---|---|---|
| CPU | 2 cores (x64 or ARM64) | 4 vCPUs |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 40 GB+ |
| OS | Ubuntu / Debian / CentOS / Amazon Linux / macOS+WSL2 | Ubuntu LTS |
| Runtime | Docker + Docker Compose (latest) | |

> For 20–50 active users: use 4 vCPU / 8 GB RAM.

## Setup Steps

```bash
# 1. Clone and switch to preview branch
git clone https://github.com/makeplane/plane.git
cd plane
git checkout preview

# 2. Configure environment
cp .env.example .env
# Edit .env: set SECRET_KEY, database credentials, storage, etc.

# 3. Start services
docker compose up -d

# 4. Access
# Web UI: http://<your-vps-ip>
# API:    http://<your-vps-ip>/api/v1/
```

## API Endpoints Available After PR #9020 (preview branch)

| Method | Endpoint |
|--------|----------|
| GET | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/` |
| POST | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/` |
| GET | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/{page_id}/` |
| PATCH | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/{page_id}/` |
| DELETE | `/api/v1/workspaces/{slug}/projects/{project_id}/pages/{page_id}/` |

## Credentials Config

Same format as Plane Cloud — update `~/.config/plane/config.json`:

```json
{
  "host": "http://<your-vps-ip>",
  "workspace": "your-workspace-slug",
  "token": "your-api-key"
}
```

`upload_project_pages.py` will work without changes once PATCH is live on the instance.
