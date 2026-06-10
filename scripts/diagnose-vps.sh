#!/usr/bin/env bash
# Print why :8081 / :8082 may be down after reboot.
set -euo pipefail

echo "========== systemd =========="
for u in docker nginx finano-app finano-pitch-sync; do
  printf "\n--- %s ---\n" "$u"
  systemctl is-enabled "$u" 2>/dev/null || echo "not installed"
  systemctl is-active "$u" 2>/dev/null || true
done

echo ""
echo "========== listening ports (8081 / 8082 / 80) =========="
if command -v ss >/dev/null 2>&1; then
  ss -tlnp | grep -E ':8081|:8082|:80 ' || echo "nothing on 8081/8082/80"
else
  netstat -tlnp 2>/dev/null | grep -E '8081|8082|:80 ' || true
fi

echo ""
echo "========== docker =========="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "docker not running"

echo ""
echo "========== pitch web root =========="
ls -la /var/www/finano-pitch-ppt/index.html 2>/dev/null || echo "missing /var/www/finano-pitch-ppt/index.html"
ls -la /opt/finano/pitch-deck/index.html 2>/dev/null || echo "missing /opt/finano/pitch-deck/index.html"
for f in /var/www/finano-pitch-ppt/assets/finano_concept.mp4 /opt/finano/pitch-deck/assets/finano_concept.mp4; do
  if [[ -f "$f" ]]; then
    ls -lh "$f"
    sz="$(wc -c < "$f" | tr -d ' ')"
    if [[ "$sz" -lt 1000000 ]]; then
      echo "WARN: $f looks like Git LFS pointer (${sz}B). Install git-lfs and run: cd /opt/finano && git lfs pull && bash scripts/sync-pitch-deck.sh"
    fi
  else
    echo "missing $f"
  fi
done
command -v git-lfs >/dev/null 2>&1 && git lfs version || echo "git-lfs not installed"

echo ""
echo "========== local curl =========="
curl -sS -o /dev/null -w "8081 product: %{http_code}\n" --connect-timeout 3 http://127.0.0.1:8081/ || echo "8081 failed"
curl -sS -o /dev/null -w "8082 pitch: %{http_code}\n" --connect-timeout 3 http://127.0.0.1:8082/ || echo "8082 failed"

echo ""
echo "URLs: http://<public-ip>:8081/  http://<public-ip>:8082/"
echo "If local curl OK but browser fails → check Tencent Cloud security group (8081, 8082)."
