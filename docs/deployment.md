# Lyftr AI Deployment Preparation

This guide prepares the existing application for a FastAPI backend on AWS EC2 and a static React/Vite frontend on Vercel. It does not deploy either service. Replace every angle-bracket placeholder with your own value; never put a Groq key in source code, a Docker image, a Vercel variable, or a command that you might paste into a shared log.

## Deployment shape

- **Vercel project root:** `frontend/`. Vercel builds the Vite app and serves the static `dist/` output. `frontend/vercel.json` sets the build command, output directory, and SPA fallback.
- **EC2:** Run only the backend image. Do not start the Compose `frontend` service on EC2. Uvicorn listens on `0.0.0.0:8000` in the container, but Docker publishes it only on the host loopback address (`127.0.0.1:8000`). A host reverse proxy terminates HTTPS and forwards requests to it.
- **SQLite:** Attach a separate EBS volume and mount it on the EC2 host at `/srv/lyftr/data`. Bind-mount that directory into the backend as `/data`; the configured database URL is `sqlite:////data/app.db`.
- **Secrets and configuration:** Store the comma-separated Groq keys in a root-owned, mode-600 environment file on EC2. The Docker image contains application code and dependencies only. `ENABLE_FAILURE_SIMULATION=false` in the server environment.
- **Browser API URL:** Set Vercel's `VITE_API_BASE_URL` to the public HTTPS API origin, for example `https://<api-domain>`. This is a public URL, not a secret. Do not set it to `http://backend:8000` or `/api` for this direct EC2 setup.

The existing backend already reads comma-separated exact origins from `ALLOWED_ORIGINS`, has a `/health` endpoint, and serves the API routes at `/chat` and `/sessions/...`. No API or application code changes are required for deployment. The existing Compose setup is for local development: `docker compose up -d backend` starts only its backend service, but the Compose named volume is not the explicit EC2 EBS mount described here. The `docker run` command below uses a host bind mount for that purpose.

## 1. Check AWS account and estimate costs

1. Sign in to the AWS account and choose the region closest to your users and supported by your desired instance type.
2. Before creating resources, review **Billing and Cost Management**, configure a budget alert, and use the [AWS Pricing Calculator](https://calculator.aws/) for your chosen region and expected monthly uptime.
3. Estimate at least:
   - EC2 instance hours and the selected CPU/memory size. LiteLLM calls Groq over the network, but the API and SQLite still need enough memory and disk I/O for your request volume.
   - EBS gp3 capacity and any provisioned performance beyond its included baseline; snapshots add storage charges.
   - Public IPv4 address charges, including an Elastic IP if you reserve one. An address makes DNS stable across instance stops/replacements.
   - Internet data transfer, DNS/domain registration, and optional load balancer or monitoring charges.
   - Groq model usage, which is billed separately by Groq and depends on token volume and its current pricing.
   - Vercel plan and usage. Vercel currently lists Hobby at $0/month for personal projects and Pro at $20/month plus usage rules; check the current [Vercel pricing](https://vercel.com/pricing) and plan eligibility before choosing.

AWS prices vary by region, instance type, storage, and usage. Confirm estimates in the calculator and pricing pages immediately before creating resources. Relevant references: [EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/), [VPC public IPv4 pricing](https://aws.amazon.com/vpc/pricing/), and [Vercel plans](https://vercel.com/docs/plans).

## 2. Create the EC2 instance and network rules

In the AWS Console, select **EC2 → Launch instance**:

1. Choose an Ubuntu Server 24.04 LTS AMI, select an instance architecture/type that fits your budget and expected load, and create or select a key pair. Download and protect the private key; AWS does not provide it again.
2. Configure an EBS root disk and a separate EBS data volume for SQLite. Choose a data size based on expected chat history and backup retention. Keep the data volume in the same Availability Zone as the instance.
3. Create or select a security group with these inbound rules:

   | Port | Source | Purpose |
   | --- | --- | --- |
   | TCP 22 | Your current public IP `/32` only | SSH administration |
   | TCP 80 | `0.0.0.0/0` (and `::/0` if using IPv6) | Optional HTTP redirect and certificate validation/renewal |
   | TCP 443 | `0.0.0.0/0` (and `::/0` if using IPv6) | Public HTTPS API |

   Do not add a public inbound rule for port 8000. If your IP changes, update the SSH source rule to your new IP; do not open SSH to `0.0.0.0/0`. AWS recommends restricting SSH to known addresses in its [security group guidance](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/creating-security-group.html).
4. Allocate and associate a static public IPv4 address if you need a stable DNS target. Review its current price before reserving it.
5. Attach the separate EBS data volume. Take note of its availability zone and size.

## 3. Connect and install Docker

From Windows PowerShell, connect using the downloaded key path and the instance public IP or static address:

```powershell
ssh -i "C:\path\to\your-key.pem" ubuntu@<EC2_PUBLIC_IP>
```

On the Ubuntu instance, install Docker Engine and the Compose plugin using Docker's maintained [Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/). The following is the current repository-based approach; review Docker's page if package steps change:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
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

These commands install Docker from its official apt repository. Keep Docker Engine updated. Membership in the `docker` group grants root-equivalent control of the machine; use `sudo docker` unless you consciously accept that privilege.

## 4. Mount persistent SQLite storage

The EC2 instance's container filesystem is not a suitable place for the production database. Mount the separate EBS disk on the host and bind-mount it into the backend. **Only format a brand-new, empty data volume. Formatting an existing volume erases its contents.** Confirm the target device and filesystem first:

```bash
lsblk -f
```

For a new empty volume only, substitute the actual device shown by `lsblk` (Nitro instances often use an NVMe name):

```bash
sudo mkfs.ext4 /dev/<verified-new-volume-device>
sudo mkdir -p /srv/lyftr/data
sudo mount /dev/<verified-new-volume-device> /srv/lyftr/data
```

The backend image runs as a non-root `app` user. After building the image in the next section, read its numeric UID and GID, then grant that account access to the mount:

```bash
docker run --rm --entrypoint id lyftr-ai-backend:production -u
docker run --rm --entrypoint id lyftr-ai-backend:production -g
sudo chown <APP_UID>:<APP_GID> /srv/lyftr/data
sudo chmod 0750 /srv/lyftr/data
```

Configure the volume to mount after reboot using its UUID, not an assumed device name. Find it with `sudo blkid /dev/<verified-new-volume-device>`, then add the corresponding line to `/etc/fstab`:

```text
UUID=<volume-filesystem-uuid> /srv/lyftr/data ext4 defaults,nofail 0 2
```

Verify the entry before rebooting:

```bash
sudo mount -a
df -h /srv/lyftr/data
```

AWS recommends UUID-based entries for automatic EBS mounting; see [Make an EBS volume available for use](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-using-volumes.html). Back up SQLite and take EBS snapshots on a schedule. An EBS volume is durable storage for this instance, but it does not by itself provide multi-instance availability.

## 5. Build and start only the backend

Obtain the project source on the EC2 instance from the repository or a reviewed release artifact. Keep it in a directory such as `/opt/lyftr-ai`. Build only the backend image from the project root; its Dockerfile copies `backend/app` and installs `backend/requirements.txt`:

```bash
cd /opt/lyftr-ai
sudo docker build -f backend/Dockerfile -t lyftr-ai-backend:production .
```

Create a protected environment file. Do not place real keys in a command line, checked-in file, or Docker build argument:

```bash
sudo install -d -m 0750 /etc/lyftr
sudo install -m 0600 /dev/null /etc/lyftr/backend.env
sudo nano /etc/lyftr/backend.env
```

Enter these settings in the editor, replacing placeholders locally. Put both Groq keys in `LLM_API_KEYS`, comma-separated, with no spaces required. Add the exact Vercel production origin after the first Vercel deployment has assigned its stable production domain:

```dotenv
LLM_PROVIDER=groq
LLM_MODEL=groq/openai/gpt-oss-120b
LLM_API_KEYS=<GROQ_KEY_1>,<GROQ_KEY_2>
DATABASE_URL=sqlite:////data/app.db
ALLOWED_ORIGINS=https://<your-production-project>.vercel.app
ENABLE_FAILURE_SIMULATION=false
CACHE_ENABLED=true
LITELLM_CACHE_TYPE=local
```

If you add a custom Vercel domain, include each exact allowed origin as a comma-separated item, such as `https://<project>.vercel.app,https://<your-custom-domain>`. Origins include the scheme and hostname, and must not include a path. Do not use `*`. The backend parses these as explicit origins; the CORS code does not need a change.

Start the backend with a host bind mount for the EBS-backed directory. Binding to `127.0.0.1` means only the host reverse proxy can reach port 8000; the public security group does not expose it:

```bash
sudo docker run -d \
  --name lyftr-ai-backend \
  --restart unless-stopped \
  --env-file /etc/lyftr/backend.env \
  --publish 127.0.0.1:8000:8000 \
  --mount type=bind,src=/srv/lyftr/data,dst=/data \
  --health-cmd='python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/health\", timeout=3)"' \
  --health-interval=30s --health-timeout=5s --health-retries=3 --health-start-period=20s \
  lyftr-ai-backend:production
```

The image starts Uvicorn on `0.0.0.0:8000` inside the container, as required for Docker networking. Docker's host binding limits access to the host loopback interface. The `unless-stopped` policy restarts the backend after Docker/EC2 restarts. Only the backend is started; no frontend container is needed.

Check container status without printing environment variables:

```bash
sudo docker ps --filter name=lyftr-ai-backend
sudo docker inspect --format '{{.State.Health.Status}}' lyftr-ai-backend
curl -i http://127.0.0.1:8000/health
```

The health endpoint returns 200 when SQLite is reachable and at least one key is configured. It returns 503 if no key is configured; health does not verify that Groq accepts the keys. Do not paste environment values or full container environment inspection output into support tickets.

## 6. Add HTTPS with a domain and reverse proxy

Choose a domain you control, create an `A` record such as `api.<your-domain>` pointing at the EC2 static public IP, and wait for DNS to resolve. Install a host-level reverse proxy and certificate tool:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

Create an Nginx site, replacing the example hostname with your API domain:

```bash
sudo tee /etc/nginx/sites-available/lyftr-api >/dev/null <<'EOF'
server {
    listen 80;
    server_name api.<your-domain>;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
sudo ln -s /etc/nginx/sites-available/lyftr-api /etc/nginx/sites-enabled/lyftr-api
sudo nginx -t
sudo systemctl reload nginx
```

Request a certificate after DNS resolves and the security group allows inbound port 80:

```bash
sudo certbot --nginx -d api.<your-domain>
sudo certbot renew --dry-run
```

Certbot configures TLS and renewal for Nginx. Configure the proxy to:

1. Listen publicly on ports 80 and 443 for the API domain.
2. Redirect HTTP to HTTPS and renew the TLS certificate automatically.
3. Forward HTTPS requests to `http://127.0.0.1:8000` and preserve the `Host` and `X-Forwarded-For` headers.
4. Keep port 8000 private to the host. Do not publish it on `0.0.0.0` or add it to the EC2 security group.

For Nginx, the core upstream directive is `proxy_pass http://127.0.0.1:8000;` inside the matching `location /` block. Use an HTTPS certificate from a trusted certificate authority; do not send the frontend's API requests over plain HTTP. An AWS load balancer with a managed certificate is another option, but it adds AWS resources and charges. The required Vercel CORS origin is still the Vercel frontend origin, even when a proxy terminates TLS.

## 7. Import the frontend into Vercel

1. In Vercel, choose **Add New → Project**, connect the GitHub account/repository, and import the Lyftr AI repository.
2. Set **Root Directory** to `frontend` and confirm Vercel uses that folder. The included `frontend/vercel.json` specifies `npm run build`, `dist`, and the SPA fallback to `index.html`; dependencies come from `frontend/package.json` and its lockfile.
3. In **Project Settings → Environment Variables**, add:

   | Name | Value | Environment |
   | --- | --- | --- |
   | `VITE_API_BASE_URL` | `https://<your-api-domain>` | Production (and Preview only if that preview origin is allowed by backend CORS) |

   Use the actual HTTPS API origin, with no Docker hostname and no Groq key. Vite embeds `VITE_` variables into browser code, so this variable must contain only the public API base URL. The app appends `/chat` and session history paths to it.
4. Deploy the project. Once Vercel assigns the production URL, set that exact origin in the EC2 `ALLOWED_ORIGINS` file. Restart the backend to load the updated environment:

   ```bash
   sudo docker rm -f lyftr-ai-backend
   # Re-run the docker run command from the previous section with the same
   # image, env file, health settings, and /srv/lyftr/data bind mount.
   ```

   `docker rm -f` removes only the container; it does not remove the host data directory. Confirm the new container is healthy before testing the frontend. Update Vercel's variable and redeploy if the API domain changes; Vercel applies build variables to new deployments.

Vercel's official [Vite deployment guide](https://vercel.com/docs/frameworks/frontend/vite) documents `VITE_` build variables and SPA rewrites. The explicit rewrite in `frontend/vercel.json` is ready for deep links if the frontend later adds client-side routes.

## 8. Verify public endpoints

After DNS, TLS, and CORS are configured:

```bash
curl -i https://<your-api-domain>/health
```

With keys configured and the database reachable, expect HTTP 200 with `status: ok`. The Vercel site should load over HTTPS. Send a chat message through the UI and check the browser developer tools' Network panel: the request should go to `https://<your-api-domain>/chat`, receive a successful response, and show no CORS or mixed-content error. The browser must never request `backend:8000`.

For a CORS preflight check, substitute the exact Vercel origin:

```bash
curl -i -X OPTIONS 'https://<your-api-domain>/chat' \
  -H 'Origin: https://<your-production-project>.vercel.app' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```

The response should include an `Access-Control-Allow-Origin` matching that exact origin. Do not use the Groq key in a frontend request.

## 9. Update, rollback, and troubleshoot

For an update, build a new tagged image (for example `lyftr-ai-backend:<release>`), then stop and remove the old container and start the new image using the same environment file and EBS bind mount. Keep the prior image tag until the new version passes health and chat checks. To roll back, recreate the container using the prior image tag and the same `/etc/lyftr/backend.env` and `/srv/lyftr/data` mount. Never remove `/srv/lyftr/data` during a code rollback.

Useful diagnostics that do not print the environment file:

```bash
sudo docker ps -a --filter name=lyftr-ai-backend
sudo docker logs --tail 100 lyftr-ai-backend
sudo docker inspect --format '{{.State.Health.Status}}' lyftr-ai-backend
df -h /srv/lyftr/data
sudo ls -ld /srv/lyftr/data
sudo systemctl status docker
```

- **Container exits or is unhealthy:** inspect recent application logs and `docker inspect` health status. Verify the env file's permissions and variable names without copying its contents into a chat or ticket.
- **Health returns 503:** confirm the data volume is mounted and writable and that `LLM_API_KEYS` contains keys; health does not validate keys with Groq.
- **SQLite “readonly” or permission errors:** check that the correct EBS volume is mounted at `/srv/lyftr/data` and the directory is writable by the container image's numeric app UID/GID.
- **Vercel reports API network/CORS errors:** check that the Vercel variable is the public `https://` API origin, the reverse proxy forwards `/chat` to the backend, port 443 is reachable, and `ALLOWED_ORIGINS` exactly matches the deployed Vercel origin. Redeploy Vercel after changing its environment variable.
- **TLS certificate fails:** verify the DNS record points to the public address and inbound ports 80/443 reach the host proxy.
- **History disappeared after a replacement:** check `findmnt /srv/lyftr/data`, `df -h /srv/lyftr/data`, the container bind mount, and that the EBS volume was reattached. Restore from a verified backup or EBS snapshot if needed.
- **Unexpected provider failures:** verify the selected Groq model and key validity/quota using the backend logs and Groq account. Never print keys while debugging.

## Security and service limits

- Root `.env` and other environment files are ignored by Git and excluded from Docker build contexts. Keep production keys only in the protected EC2 environment file or a managed secret store. Do not put Groq keys in Vercel.
- CORS is an exact origin allowlist. Add the production Vercel origin and any custom frontend domain explicitly; preview origins need their own exact entries if they must call production.
- Restrict SSH to your IP, expose only HTTPS publicly (and HTTP only for redirects/certificate validation), and keep backend port 8000 bound to host loopback.
- The current chat API has no user authentication or application-level rate limiting. Before inviting the public, add an abuse-control plan (for example authentication and rate limits at a trusted proxy/API gateway) and monitor Groq usage; otherwise anyone who can reach the endpoint may trigger model usage and costs.
- SQLite with one EC2 instance is a single-node design. Keep automated backups and snapshots and test restoration. Use maintenance windows for disk changes and database upgrades.

## Not deployed

No AWS or Vercel resources have been created by this preparation. The backend and frontend remain local until you complete the manual steps above, configure your real domains and secrets, and verify the public endpoints.
