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

## One-time VPS setup (Nginx + boot autostart + firewall)

```bash
cd /opt/finano
git pull origin main
bash scripts/install-pitch-deck-boot.sh
# Tencent Cloud security group: allow TCP 8082
```

This installs:

- `finano-pitch-sync.service` — on **every reboot**, rsync `/opt/finano/pitch-deck` → `/var/www/finano-pitch-ppt` before Nginx starts
- Nginx site on **8082**, `systemctl enable nginx` so it starts after instance restart

Verify after reboot:

```bash
sudo systemctl status finano-pitch-sync.service nginx
curl -I http://127.0.0.1:8082/
```

Install Git LFS on the VPS if video/audio are missing after deploy:

```bash
sudo apt-get update && sudo apt-get install -y git-lfs
cd /opt/finano && git lfs install && git lfs pull
```

## Local edit

Edit files in `pitch-deck/`, commit to FINANO `main`, push — no separate FINANOPITCHPPT repo required.
