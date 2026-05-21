# FINANO Pitch Deck (in-repo)

Static HTML presentation lives under **`pitch-deck/`** in the main [FINANO](https://github.com/Sylvia2001vck/FINANO) repository.

## Live URL

http://43.129.199.236:8082/

## CI/CD

Uses the **same GitHub Actions secrets** as the product deploy (`.github/workflows/deploy.yml`):

- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PORT`, `SSH_PASSPHRASE`

On every push to `main`:

1. Product deploy runs (`scripts/vps-deploy.sh`)
2. `pitch-deck/` is rsynced to `/var/www/finano-pitch-ppt/` on the VPS

## One-time VPS setup (Nginx + firewall)

```bash
cd /opt/finano
bash scripts/setup-pitch-deck-nginx.sh
# Tencent Cloud security group: allow TCP 8082
```

Install Git LFS on the VPS if video/audio are missing after deploy:

```bash
sudo apt-get update && sudo apt-get install -y git-lfs
cd /opt/finano && git lfs install && git lfs pull
```

## Local edit

Edit files in `pitch-deck/`, commit to FINANO `main`, push — no separate FINANOPITCHPPT repo required.
