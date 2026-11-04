# Deploy Forma to Aliyun ECS at https://www.riskcat.cn/forma/

This guide adds Forma to an ECS server that already runs Nginx and other applications. Commands assume **Ubuntu 24.04 LTS, systemd, and sudo access**. On Alibaba Cloud Linux or another distribution, adapt package installation and Nginx include paths; the application settings and routing stay the same. No changes to the server have been made by adding this guide.

## 1. Deployment layout

| Purpose | Location |
| --- | --- |
| Studio | `https://www.riskcat.cn/forma/` |
| Backend, reachable only on the ECS machine | `127.0.0.1:8108` |
| Code / dedicated Python environment | `/opt/forma` / `/opt/forma/.venv` |
| Dedicated Node.js 24 installation | `/opt/forma/node` |
| **Only loaded environment file** | `/opt/forma/backend/.env` |
| Persistent databases, projects, and runtime files | `/var/lib/forma` |
| Service account / systemd service | `forma` / `forma.service` |
| Generated app and preview hosts | `*.forma-apps.riskcat.cn` |

Nginx forwards `/forma/` to Forma and removes that prefix. FastAPI serves both the built frontend and API. Existing `/`, `/api`, `/assets`, and other application locations are preserved. Run **one backend worker**: runtime ownership and active jobs include in-process state, and storage uses local SQLite.

Generated apps require separate browser origins. A public app has a URL such as `https://app-<id>.forma-apps.riskcat.cn/apps/<project-id>/`; previews have their own `preview-…` hosts. They cannot all be placed under `www.riskcat.cn/forma/`, because that would share the studio's browser storage and permissions. Other applications already on `www.riskcat.cn` share the studio's origin regardless of path, so those should be trusted applications.

Before proceeding:

- Confirm port `8108` is unused (`sudo ss -ltnp`) and the machine has spare memory, disk, and CPU for builds and generated app runtimes.
- Keep the existing `www.riskcat.cn` DNS record and HTTPS certificate. Add a wildcard A record **`*.forma-apps.riskcat.cn`** pointing to this ECS public IP (DNS console host field: `*.forma-apps`). Add AAAA only if IPv6 is configured end to end.
- Obtain a certificate covering **`*.forma-apps.riskcat.cn`**, using your existing certificate process or DNS verification. A certificate for `*.riskcat.cn` does **not** cover these deeper names. Configure renewal and Nginx reload with the certificate provider.
- Expose public HTTP/HTTPS ports 80/443. Keep `8108`, generated runtime ports, and databases private; preserve the current restricted SSH policy. See [Aliyun security group rules](https://www.alibabacloud.com/help/en/ecs/user-guide/security-group-rules).
- For mainland China ECS hosting, confirm that the domain and service are covered by the applicable ICP filing before launch; see [Aliyun's ICP guidance](https://www.alibabacloud.com/en/icp).

## 2. Install Forma alongside the existing applications

On the ECS machine, create a dedicated account and directories. Skip account creation if it already exists.

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip build-essential curl ca-certificates xz-utils rsync nano
sudo useradd --system --create-home --home-dir /var/lib/forma --shell /usr/sbin/nologin forma
sudo install -d -o forma -g forma -m 0755 /opt/forma
sudo install -d -o forma -g forma -m 0750 /var/lib/forma
```

From your local repository directory, upload source to a staging folder. Replace `DEPLOY_USER` and `ECS_IP`. Do not upload the local Python environment, dependency folders, data, or credentials with this command.

```bash
rsync -az \
  --exclude=.git/ --exclude=.env --exclude=.venv/ --exclude=python_env/ \
  --exclude=node_modules/ --exclude=frontend/dist/ --exclude=data/ \
  --exclude=__pycache__/ --exclude=.pytest_cache/ --exclude='*.tsbuildinfo' \
  --exclude=frontend/test-results/ --exclude=frontend/playwright-report/ \
  ./ DEPLOY_USER@ECS_IP:/tmp/forma-release/
```

Back on ECS:

```bash
sudo rsync -a --chown=forma:forma /tmp/forma-release/ /opt/forma/
sudo -u forma python3 -m venv /opt/forma/.venv
sudo -u forma /opt/forma/.venv/bin/python -m pip install --upgrade pip
sudo -u forma /opt/forma/.venv/bin/python -m pip install -r /opt/forma/backend/requirements.txt
```

### Dedicated Node.js 24

Keep the existing applications' Node installation unchanged. Download an official Node.js 24 Linux archive into a temporary directory and check its published checksum. The following selects x64 or ARM64 automatically; see the [official Node.js downloads](https://nodejs.org/en/download).

```bash
FORMA_NODE_TMP=$(mktemp -d)
cd "$FORMA_NODE_TMP"
case "$(uname -m)" in
  x86_64) FORMA_NODE_ARCH=x64 ;;
  aarch64) FORMA_NODE_ARCH=arm64 ;;
  *) echo 'Unsupported CPU architecture'; exit 1 ;;
esac
curl -fsSLO https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt
FORMA_NODE_ARCHIVE=$(awk -v suffix="-linux-${FORMA_NODE_ARCH}.tar.xz" '$2 ~ suffix "$" {print $2}' SHASUMS256.txt)
test -n "$FORMA_NODE_ARCHIVE"
curl -fsSLO "https://nodejs.org/dist/latest-v24.x/$FORMA_NODE_ARCHIVE"
sha256sum --check --ignore-missing SHASUMS256.txt
# Continue only if the checksum reports OK.
sudo install -d /opt/forma/node
sudo tar -xJf "$FORMA_NODE_ARCHIVE" --strip-components=1 -C /opt/forma/node
/opt/forma/node/bin/node --version
```

### Generated backend isolation

Use `SANDBOX_V1=true` for generated FastAPI apps. If Docker Engine is not installed, follow the [official Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/). Reuse an existing working Docker installation; do not reinstall it or prune other applications' images/containers.

```bash
sudo usermod -aG docker forma
sudo -u forma docker info
sudo -u forma docker pull python:3.13-slim
```

If image downloads fail from this ECS region, configure your approved registry/mirror before enabling generated backends. The `forma` account must be able to use the local Docker daemon. Membership of the Docker group grants root-level privileges to that service account; see [Docker's Linux post-installation guidance](https://docs.docker.com/engine/install/linux-postinstall/).

Generated containers have resource and filesystem limits, but this release does not provide full hostile multi-tenant isolation or outbound network restrictions. Use administrator-approved users on this shared ECS machine. For untrusted public workloads, use a separate host from sensitive existing applications. `RUNTIME_MAX_PROCESSES` limits active app runtimes, not all build resource use.

## 3. Configure the single backend/.env

For a fresh installation only:

```bash
sudo -u forma cp -n /opt/forma/.env.example /opt/forma/backend/.env
sudo chmod 600 /opt/forma/backend/.env
sudo -u forma nano /opt/forma/backend/.env
```

Set these values in that file, keeping each setting only once:

```dotenv
SECRET_KEY=REPLACE_WITH_A_LONG_RANDOM_SECRET
DATA_DIR=/var/lib/forma
STUDIO_BASE_URL=https://www.riskcat.cn
STUDIO_PATH_PREFIX=/forma
CORS_ORIGINS=https://www.riskcat.cn
APPS_BASE_URL=https://forma-apps.riskcat.cn
RUNTIME_PYTHON=/opt/forma/.venv/bin/python
RUNTIME_MAX_PROCESSES=2
RUNTIME_MEMORY_MB=768
SANDBOX_V1=true
DURABLE_JOBS_V1=false
ACCEPTANCE_GATE_V1=false
```

`STUDIO_BASE_URL` and `CORS_ORIGINS` are **origins only**, without `/forma`. The prefix has its own setting. Two runtimes is an initial limit for sharing an existing server; adjust after measuring available capacity. The other feature flags preserve the default generation behavior; retain deliberately enabled flags when migrating an existing installation.

For a **new database**, generate a secret with `/opt/forma/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'` and paste it into the file. For existing data, retain its original `SECRET_KEY`: changing it makes saved provider credentials unreadable and invalidates tokens and pending verification challenges. Back it up securely with the data.

Transfer your configured SMTP/SMS settings securely into this same file. Enable at least one delivery channel. Registration and password recovery reuse those settings, including the optional `ALIYUN_SMS_PASSWORD_RESET_TEMPLATE_CODE`. For email, use the provider's TLS settings, typically SSL on port 465; ECS restricts outbound port 25 by default. See [Aliyun's port guidance](https://www.alibabacloud.com/help/en/ecs/user-guide/security-group-rules).

Do not create `/opt/forma/.env` or a frontend `.env`. The service does not use systemd `EnvironmentFile`; Python reads `/opt/forma/backend/.env` directly. Exported process variables take precedence, so check the startup report if a value seems ignored. Restart `forma` after editing configuration.

## 4. Build for /forma and secure the initial administrator

```bash
cd /opt/forma/frontend
sudo -u forma env PATH=/opt/forma/node/bin:/usr/local/bin:/usr/bin:/bin npm ci
sudo -u forma env PATH=/opt/forma/node/bin:/usr/local/bin:/usr/bin:/bin npm run build -- --base=/forma/
```

Use the `/forma/` base on **every production build**. It sets frontend assets, browser routing, API requests, live event streams, downloads, and the favicon beneath `/forma/`. The default build remains suitable for local root hosting. See [Vite's public base-path documentation](https://vite.dev/guide/build).

On a fresh database, replace the built-in `admin@forma.local` / `admin123` account **before adding the public Nginx route**. This local command prompts for a real email and a new password, preserves the account ID, and invalidates its old sessions. It changes only the bootstrap administrator; if that account was already replaced, sign in with your existing administrator instead.

```bash
cd /opt/forma/backend
sudo -u forma /opt/forma/.venv/bin/python -c '
from getpass import getpass
from email_validator import validate_email
from app.database import init_databases, control_db
from app.security import hash_password

init_databases()
with control_db() as db:
    admin = db.execute("SELECT id FROM users WHERE email=? AND role=?", ("admin@forma.local", "admin")).fetchone()
if admin is None:
    raise SystemExit("Bootstrap administrator was already replaced; use your existing account.")
email = validate_email(input("Administrator email: ").strip(), check_deliverability=False).normalized.lower()
password = getpass("New password (12–128 characters): ")
if not 12 <= len(password) <= 128 or password != getpass("Repeat password: "):
    raise SystemExit("Password length or confirmation is invalid; no account was changed.")
with control_db() as db:
    db.execute("UPDATE users SET email=?,password_hash=?,session_version=session_version+1 WHERE id=?",
               (email, hash_password(password), admin["id"]))
print("Administrator updated.")
'
```

The email is set locally by the server operator; this command does not send a verification message. Confirm the address carefully so password recovery can reach it.

## 5. Start the Forma service

```bash
sudo install -m 0644 /opt/forma/deploy/forma.service /etc/systemd/system/forma.service
sudo systemctl daemon-reload
sudo systemctl enable --now forma
sudo systemctl status forma --no-pager
curl --fail -H 'Host: www.riskcat.cn' http://127.0.0.1:8108/api/health
sudo journalctl -u forma -n 80 --no-pager
```

The service uses one worker, no development reload, and only loopback networking. Leave `--root-path` unset: Nginx strips the studio prefix, while generated hosts keep their original paths. The `Host` header in the local health check is required because Forma rejects unknown hosts. Startup logs identify the one active environment file and the effective feature flags without logging credential values.

## 6. Add Nginx routes without replacing existing applications

Find the active HTTPS `server` block for `www.riskcat.cn` in your current Nginx configuration (`sudo nginx -T`, inspected locally). Back up the files you will edit. Do **not** add a second competing `server_name www.riskcat.cn` block or replace its root location.

Install the studio snippet:

```bash
sudo install -d /etc/nginx/snippets
sudo install -m 0644 /opt/forma/deploy/nginx/forma-location.conf /etc/nginx/snippets/forma-location.conf
```

Inside the **existing HTTPS server block** for `www.riskcat.cn`, add:

```nginx
include /etc/nginx/snippets/forma-location.conf;
```

The snippet redirects `/forma` to `/forma/`, then proxies only that subtree. Its `proxy_pass http://127.0.0.1:8108/;` trailing slash removes the matched prefix; `/forma/api/health` becomes `/api/health`. Buffering and proxy caching are disabled so generation progress streams immediately. These behaviors follow [Nginx's proxy module documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

Install the generated-app server template into a directory your main Nginx configuration includes in the `http` context; `/etc/nginx/conf.d/*.conf` is a common choice:

```bash
sudo install -m 0644 /opt/forma/deploy/nginx/forma-apps.conf.example /etc/nginx/conf.d/forma-apps.conf
sudo nano /etc/nginx/conf.d/forma-apps.conf
```

Replace the certificate paths with the actual wildcard certificate and private key paths. This separate server preserves the original `/apps/...` and `/preview/...` paths and incoming `Host`. Access logs are disabled on generated hosts because preview paths contain temporary grants. Avoid recording their full URLs in additional CDN/WAF logs.

Review inherited security headers: a studio policy such as `frame-src 'self'` must also allow `https://*.forma-apps.riskcat.cn`. Do not impose `X-Frame-Options: DENY` or `SAMEORIGIN` on generated preview responses; Forma supplies the preview's allowed parent origin. Keep normal security settings for the other existing applications.

Validate before reloading:

```bash
sudo nginx -t
# Run only if the configuration test succeeds:
sudo systemctl reload nginx
```

The template does not change global `/api`, `/assets`, server defaults, or another application's certificate. Test the existing applications after the reload as well.

## 7. Verify the public deployment

```bash
curl -I https://www.riskcat.cn/forma
curl --fail https://www.riskcat.cn/forma/api/health
curl -I https://www.riskcat.cn/forma/forma.svg
curl -I https://www.riskcat.cn/forma/login
curl -I https://www.riskcat.cn/forma/forgot-password
```

Expect a redirect for `/forma`, successful health JSON, and HTTP 200 for the icon and frontend pages. In a browser:

1. Sign in with your administrator and confirm the Forma tab icon. Refresh `/forma/settings` and a project URL directly.
2. Configure the global model and **Admin → Studio policy** (default five projects per user and one hour hosting, configurable up to 8,760 hours).
3. Send a registration code to an email/mobile you control, verify it, and approve the pending account in User management. Test password recovery through the same configured delivery channel.
4. Create a small application. Confirm progress updates arrive while generation runs and source downloads work.
5. Preview and publish an app. Confirm its generated HTTPS hostname resolves and has a valid certificate. Test a FastAPI app too, checking its Server panel and `sudo -u forma docker ps` for a working runtime.
6. Confirm the existing websites still work. Close and reopen the browser tab if it retains an old favicon.

For a wildcard routing check, `curl -I https://probe.forma-apps.riskcat.cn/` should complete TLS and return 404: this is an unrecognized app host, so a rejection is expected. Use a real generated URL to test app content; do not publish preview URLs in tickets or logs.

## 8. Backups, upgrades, and rollback

Back up **all of `/var/lib/forma` plus `/opt/forma/backend/.env`** to restricted storage. For a consistent filesystem backup, briefly stop only `forma`, archive those paths, then start it again. This includes the control database, user databases, app databases, projects, and the encryption key. Keep the matching code revision or release archive. Do not back up a live SQLite file alone while writes continue.

For upgrades, stage the next source release separately, preserve the current release and data backup, then stop `forma`. Copy the new source into `/opt/forma` while preserving `backend/.env`, the dedicated Node installation, and the Python environment. Install requirements, run `npm ci`, rebuild with `--base=/forma/`, and restart `forma`. Check health and the browser flow. Reload Nginx only when its configuration changes. Database upgrades happen on startup; rollback may require restoring the matching data backup together with the previous release.

If migrating local data from macOS, stop the local application and transfer the full persistent data tree and its original `SECRET_KEY` securely. Do not reuse macOS Python virtual environments, Node dependency caches, symlinks, or runtime process metadata on Linux; rebuild those runtime dependencies on ECS. Keep the original backup until previews, published apps, and saved app data have been checked. A fresh installation starts with an empty workspace; existing accounts and projects are not transferred by the source upload in step 2.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Nginx 502 | `systemctl status forma`, `journalctl -u forma`, loopback port 8108, and the local health check with the correct Host header. |
| Blank page or requests to `/assets` or `/api` | Rebuild with `--base=/forma/`; confirm the studio Nginx `proxy_pass` ends in `/`; hard-refresh stale HTML. |
| Refreshing login/reset/project pages returns 404 | Confirm this release is deployed, the frontend build exists, and `/forma/` reaches FastAPI rather than a separate static root. |
| Studio works but preview fails | Wildcard DNS, wildcard certificate depth, generated-host Nginx block, unchanged Host header, and inherited frame headers. |
| Configuration appears ignored | Only `/opt/forma/backend/.env` is loaded; inspect reported process override names and restart the service. |
| Registration/reset code is not received | Delivery flags, SMTP TLS/port, RAM SMS permissions, approved sign/templates, account quota, and service logs. Never log codes or secrets. |
| FastAPI app cannot start | Docker access as `forma`, base image availability, package mirror connectivity, disk/memory limits, and the app's Server panel. |
| Published app returns 410 | Its hosting period expired; renew it in Forma or adjust the admin policy for future publications. |

Local validation of this release uses a prefix-stripping test proxy and browser tests. Run `npm run build -- --base=/forma/` followed by `npx playwright test --config playwright.subpath.config.ts` from `frontend` (set `FORMA_TEST_PYTHON` to your backend Python executable if needed). Actual ECS DNS, certificates, and Nginx must still be validated on the target server.
