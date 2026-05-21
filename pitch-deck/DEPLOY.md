# FINANO Pitch Deck (in-repo)

Static HTML presentation lives under **`pitch-deck/`** in the main [FINANO](https://github.com/Sylvia2001vck/FINANO) repository.

## Live URL

http://43.129.199.236:8082/

## CI/CD

Uses the **same GitHub Actions secrets** as the product deploy (`.github/workflows/deploy.yml`):

- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PORT`, `SSH_PASSPHRASE`

On push to `main`:

| What changed | CI job | Typical time |
|--------------|--------|----------------|
| Only `pitch-deck/**` | **deploy-pitch-deck** (git pull + rsync) | ~1–2 min |
| `frontend/`, `backend/`, Docker, etc. | **deploy-app** (npm + `docker build` + pip) | 10–30+ min |

The long log lines (`Downloading … whl`, `Installing collected packages`) come from **backend Docker image rebuild**, not from the HTML pitch deck.

## One-time VPS setup (reboot autostart + firewall)

```bash
cd /opt/finano
git pull origin main
chmod +x scripts/*.sh
bash scripts/install-vps-boot-all.sh
```

Installs:

- **`finano-app.service`** — Docker Compose product on **:8081** after reboot
- **`finano-pitch-sync.service`** + Nginx — pitch deck on **:8082**
- `systemctl enable docker nginx`

Tencent Cloud security group: allow **TCP 8081** and **8082** (not only 80).

## After reboot shows「未发送任何数据」?

Usually nothing is listening on **8082** (Nginx not installed/enabled, or one-time boot setup never ran).

```bash
cd /opt/finano && git pull origin main
bash scripts/ensure-pitch-8082.sh      # quick fix: sync + nginx :8082
bash scripts/diagnose-vps.sh
bash scripts/install-vps-boot-all.sh   # if systemd units missing
```

## `mkdir: cannot create directory '/var/www/finano-pitch-ppt': Permission denied`

GitHub Actions SSH 用户默认不能写 `/var/www`。在 VPS 用**同一部署账号**执行一次：

```bash
cd /opt/finano && git pull origin main
bash scripts/ensure-pitch-8082.sh
```

## 为什么只改 PPT 却跑了 Docker（deploy-app）？

若同一次 commit 还包含 `scripts/**`（旧规则）或 `frontend/`、`deploy.yml` 等，CI 会走慢路径。日常路演请**只提交 `pitch-deck/**`**，或用 `finano-pitch-deck` 的 `push-pitch.ps1`。

## GitHub Actions `drone-scp` / `wait: remote command exited`

Often happens if the VPS was **rebooting** during **deploy-app** (uploading `frontend-dist.tgz`). Wait ~2 minutes, re-run the failed workflow; avoid rebooting the instance during deploy.

Use correct URLs:

- Product: http://43.129.199.236:8081/
- Pitch: http://43.129.199.236:8082/

Opening `http://43.129.199.236` without port hits **:80**, which may be empty.

## Intro video / BGM not playing (black screen on slide 1)

`finano_concept.mp4` (~16 MB) and `finano.mp3` are stored with **Git LFS**. If the VPS never ran `git lfs pull`, the synced file is only a **pointer** (~130 bytes) — the page loads but the video cannot play.

```bash
sudo apt-get update && sudo apt-get install -y git-lfs
cd /opt/finano && git lfs install && git lfs pull
bash scripts/sync-pitch-deck.sh
ls -lh /var/www/finano-pitch-ppt/assets/finano_concept.mp4   # should be ~16M, not ~130 bytes
curl -I http://127.0.0.1:8082/assets/finano_concept.mp4      # expect HTTP 200
```

Then hard-refresh the browser (Ctrl+F5). `sync-pitch-deck.sh` now runs `git lfs pull` automatically when `git-lfs` is installed.

## Local edit

Edit files in `pitch-deck/`, commit to FINANO `main`, push — no separate FINANOPITCHPPT repo required.
