# Lyftr AI: Vercel + EC2 Quick Tunnel Deployment

This guide uses Vercel for the React/Vite frontend, EC2 for the FastAPI Docker Compose backend, the existing SQLite Docker volume at `/data`, Groq for inference, and a Cloudflare Quick Tunnel for temporary HTTPS. It requires no custom domain and creates no resources automatically.

Quick Tunnels are temporary and intended for testing/development. The URL changes if recreated, has no uptime guarantee, and anyone with the URL can access the API. See [Cloudflare Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Confirmed project behavior

- `frontend/src/api.js` reads `VITE_API_BASE_URL`, trims a trailing slash, and calls `<base>/chat`. It accepts a public HTTPS URL and does not hardcode a Docker hostname.
- FastAPI reads comma-separated `ALLOWED_ORIGINS` and uses exact CORS origin matching. Use the Vercel Production URL including `https://`, with no path or trailing slash.
- Uvicorn listens on `0.0.0.0:8000` inside the backend container. Compose publishes it as `127.0.0.1:8000:8000`, so `cloudflared` on EC2 can reach it but direct internet clients cannot.
- Compose's named volume `lyftr_ai_sqlite_data` mounts at `/data`; the database URL is `sqlite:////data/app.db`. Docker stores that volume on the EC2 EBS-backed root filesystem. It survives container replacement and `docker compose down` without `-v`, plus EC2 stop/start. Never run `docker compose down -v` or remove the volume. Before terminating the instance, snapshot or preserve the root disk; termination can delete it.
- `docker compose up --build -d backend` starts only the backend; no EC2 frontend container is needed.

## Before starting

Create the EC2 instance and Vercel project manually. Use Ubuntu 24.04 LTS and an EBS-backed root disk with enough capacity for Docker images and chat history. Retain or snapshot the disk before terminating the instance.

EC2 security group inbound rules:

| Port | Source | Reason |
| --- | --- | --- |
| TCP 22 | Your current public IP `/32` | SSH administration |
| No other inbound ports | — | Tunnel is initiated outbound; do not open 8000, 80, or 443 |

Leave outbound internet access enabled for Ubuntu packages, Groq, and Cloudflare. Cloudflare Tunnel uses outbound UDP or TCP port `7844`; UDP is preferred and TCP is the fallback. See [Cloudflare tunnel firewall requirements](https://developers.cloudflare.com/tunnel/configuration/).

## Commands and steps in execution order

### 1. Connect to EC2

From Windows PowerShell, replace the key path and address with your instance values:

```powershell
ssh -i "C:\path\to\your-key.pem" ubuntu@<EC2_PUBLIC_IP>
```

Run remaining shell commands in the EC2 SSH session.

### 2. Install Docker Engine and Compose plugin

Use Docker's official Ubuntu repository:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

Reference: [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

### 3. Get the project onto EC2

Replace the repository placeholder with your GitHub clone URL. For a private repository, configure SSH access or another approved source download method first.

```bash
cd /opt
sudo git clone https://github.com/<OWNER>/<REPOSITORY>.git lyftr-ai
sudo chown -R ubuntu:ubuntu /opt/lyftr-ai
cd /opt/lyftr-ai
```

These commands download the existing project; they do not commit or push.

Because the repository change in this workspace is intentionally not being pushed, update the cloned Compose file on EC2 to bind port 8000 to loopback. This one-line edit keeps the backend reachable to the local tunnel but not directly through EC2's network interfaces:

```bash
cd /opt/lyftr-ai
sed -i 's/"8000:8000"/"127.0.0.1:8000:8000"/' docker-compose.yml
grep -n '127.0.0.1:8000:8000' docker-compose.yml
```

### 4. Create the Vercel project and get its Production URL

In Vercel, import the GitHub repository and set **Root Directory** to `frontend`. In Build Settings, use Install Command `npm ci`, Build Command `npm run build`, and Output Directory `dist` (Framework Preset: Vite). Deploy once so Vercel assigns the stable Production URL, such as `https://<project>.vercel.app`. The frontend builds before its API URL is configured, but chat remains unavailable until Step 9. The current app has no client-side deep routes, so it does not require an SPA rewrite for this deployment.

Use the stable Production URL for CORS, not a Preview URL. Complete this step before editing `.env` on EC2.

### 5. Configure backend environment safely

On EC2, create the root `.env` from its placeholder example and restrict its permissions:

```bash
cd /opt/lyftr-ai
cp .env.example .env
chmod 600 .env
nano .env
```

In the editor, set the following values. Type both actual Groq keys directly into the EC2 editor as a comma-separated list; never place them in a command, Vercel, or a message. Replace the Vercel URL with the exact Production URL from Step 4.

```dotenv
LLM_PROVIDER=groq
LLM_MODEL=groq/openai/gpt-oss-120b
LLM_API_KEYS=<GROQ_KEY_1>,<GROQ_KEY_2>
DATABASE_URL=sqlite:////data/app.db
ALLOWED_ORIGINS=https://<project>.vercel.app
ENABLE_FAILURE_SIMULATION=false
CACHE_ENABLED=true
LITELLM_CACHE_TYPE=local
```

Save and exit `nano` with **Ctrl+O**, Enter, then **Ctrl+X**. `.env` is ignored by Git and excluded from Docker build context. Never run `cat .env`, `docker compose config` without `--quiet`, or a full environment inspection; those can expose secrets.

### 6. Start only the backend

Build and start only the backend. This uses the existing named volume mounted at `/data` and leaves Compose's frontend stopped:

```bash
cd /opt/lyftr-ai
sudo docker compose up --build -d backend
sudo docker compose ps
sudo docker compose exec -T backend python -c "import os; print(os.path.isfile('/data/app.db'))"
curl -i http://127.0.0.1:8000/health
```

Health should return HTTP 200 and `status: ok` when SQLite is writable and a key is configured. If health returns 503, verify `.env` in the editor without copying its contents into chat. Compose restarts the backend with `unless-stopped`; Docker is enabled at EC2 boot.

The named volume resides on the EC2 EBS-backed root disk. Container rebuilds and `docker compose down` preserve it. Do not add `-v` to `docker compose down`.

### 7. Install `cloudflared`

Install from Cloudflare's official Debian/Ubuntu package repository:

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update
sudo apt-get install -y cloudflared
cloudflared --version
```

Reference: [Cloudflare's Linux package instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/).

### 8. Start the Quick Tunnel and copy its URL

Run this in the EC2 SSH terminal and leave it running:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy the generated URL, which looks like `https://random-words.trycloudflare.com`. Do not close this SSH terminal while using the app; stopping the process stops the public URL. Open a second SSH terminal for verification.

Quick Tunnels have no uptime guarantee, the hostname changes when recreated, and anyone with the URL can reach the API. The current chat API has no authentication or rate limiting. Treat this as a temporary assignment/demo endpoint and stop it when finished. Cloudflare documents a 200 in-flight request limit and no Server-Sent Events support; this app's chat flow does not use SSE.

### 9. Set Vercel's API URL and redeploy

In Vercel, open **Project → Settings → Environment Variables** and add:

```text
Name:  VITE_API_BASE_URL
Value: https://random-words.trycloudflare.com
For:   Production
```

Use the actual URL from Step 8 with no trailing slash, then save and redeploy Production. The browser calls the public HTTPS URL directly. Do not set `http://backend:8000`, `localhost`, or `/api`. Vite embeds `VITE_` variables in browser code, so this must contain only the public backend URL—never a Groq key.

### 10. Verify health, chat, history, and CORS

In the second EC2 SSH session, replace the placeholder with the current URL:

```bash
TUNNEL_URL=https://random-words.trycloudflare.com
curl -i "$TUNNEL_URL/health"
```

Send one harmless chat request:

```bash
curl -i -X POST "$TUNNEL_URL/chat" \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://<project>.vercel.app' \
  -d '{"session_id":"assignment-smoke-001","message":"Reply with exactly: deployment ready"}'
```

Read the saved conversation with the same session ID:

```bash
curl -i "$TUNNEL_URL/sessions/assignment-smoke-001/messages"
```

Finally, open the Vercel Production URL and send a chat message. In browser Developer Tools → **Network**, confirm the request goes to the `trycloudflare.com` HTTPS URL, `/chat` succeeds, and no CORS or mixed-content error appears. CORS must match the Vercel URL exactly. A Vercel Preview hostname is blocked unless you add that exact origin to `ALLOWED_ORIGINS` and recreate the backend.

## Restart and preserve data

To reload changed environment values, recreate only the backend; the named volume is preserved:

```bash
cd /opt/lyftr-ai
sudo docker compose up -d --force-recreate backend
```

If the tunnel process restarts, its URL may change. Update `VITE_API_BASE_URL` in Vercel and redeploy. Never run `docker compose down -v` or `docker volume rm`.

Confirm the volume and database file without showing environment values:

```bash
sudo docker volume inspect lyftr_ai_sqlite_data --format '{{.Mountpoint}}'
sudo docker compose exec -T backend python -c "import os; print('database_present:', os.path.isfile('/data/app.db'))"
```

## Changes and deployment status

- `docker-compose.yml`: backend host port now binds to loopback only (`127.0.0.1:8000:8000`). The internal Uvicorn listener and API contract are unchanged.
- `docs/deployment.md`: replaced domain/reverse-proxy instructions with this Quick Tunnel procedure.
- No AWS or Vercel resources have been created, and nothing has been deployed automatically.
