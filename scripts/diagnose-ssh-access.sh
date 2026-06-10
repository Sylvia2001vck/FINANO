#!/usr/bin/env bash
# Run on VPS (Tencent console / existing SSH session) when GitHub Actions reports:
#   ssh: handshake failed: ... read: connection reset by peer
set -euo pipefail

echo "========== SSH service =========="
systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || echo "ssh/sshd unit not found"
ss -tlnp | grep -E ':22 |:2222 ' || echo "WARN: nothing listening on 22/2222"

echo ""
echo "========== ~/.ssh permissions (deploy user: $(whoami)) =========="
if [[ -d "$HOME/.ssh" ]]; then
  stat -c '%a %n' "$HOME/.ssh" "$HOME/.ssh/authorized_keys" 2>/dev/null || ls -la "$HOME/.ssh"
  echo "--- authorized_keys (first 120 chars per line) ---"
  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    echo "${line:0:120}..."
  done < "$HOME/.ssh/authorized_keys"
else
  echo "MISSING $HOME/.ssh — GitHub Actions cannot authenticate"
fi

echo ""
echo "========== fail2ban (if installed) =========="
if command -v fail2ban-client >/dev/null 2>&1; then
  sudo fail2ban-client status sshd 2>/dev/null || sudo fail2ban-client status 2>/dev/null || true
  echo "Banned IPs (sshd):"
  sudo fail2ban-client get sshd banip 2>/dev/null || true
else
  echo "fail2ban not installed"
fi

echo ""
echo "========== recent SSH auth failures (last 40 lines) =========="
if [[ -f /var/log/auth.log ]]; then
  sudo tail -40 /var/log/auth.log | grep -Ei 'sshd|refused|reset|invalid|failed|ban' || sudo tail -20 /var/log/auth.log
else
  sudo journalctl -u ssh -u sshd -n 40 --no-pager 2>/dev/null | grep -Ei 'refused|reset|invalid|failed|ban' || \
    sudo journalctl -u ssh -u sshd -n 20 --no-pager 2>/dev/null || true
fi

echo ""
echo "========== sshd hardening hints =========="
grep -E '^(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication|MaxStartups|AllowUsers|DenyUsers)' \
  /etc/ssh/sshd_config 2>/dev/null || true

echo ""
echo "========== suggested fixes =========="
cat <<'EOF'
1. Tencent 控制台 → 主机安全 → 入侵检测/登录日志 → 查 GitHub Actions IP 是否被误拦，加白名单
2. chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys
3. GitHub Secrets → DEPLOY_SSH_KEY 必须是完整私钥（含 BEGIN/END 行）
4. Re-run 前开日志: sudo journalctl -u ssh -f
EOF
