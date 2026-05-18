#!/bin/bash
# Provisioning script for bidding FastAPI server on Ubuntu 22.04 LTS (ARM or x86).
# Run AS ubuntu user (sudo needed for system packages).
# Usage:  sudo bash setup.sh

set -euo pipefail

REPO_URL="https://github.com/YOUR_GH/dext-ax.git"   # ← change to actual repo
DEPLOY_DIR="/opt/bidding"
DOMAIN="bidding.mncapro.com"                          # ← change to actual domain
SERVICE_USER="ubuntu"

echo "==> System packages"
apt-get update
apt-get install -y python3.10 python3.10-venv python3-pip git nginx certbot python3-certbot-nginx ufw

echo "==> Firewall (open 22/80/443)"
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Clone repo into ${DEPLOY_DIR}"
if [ ! -d "${DEPLOY_DIR}" ]; then
    git clone "${REPO_URL}" "${DEPLOY_DIR}"
fi
cd "${DEPLOY_DIR}"
# If repo has multi-project layout, cd into bidding subdir
if [ -d "projects/bidding" ]; then
    DEPLOY_DIR="${DEPLOY_DIR}/projects/bidding"
fi

echo "==> Python venv + deps"
python3.10 -m venv "${DEPLOY_DIR}/.venv"
"${DEPLOY_DIR}/.venv/bin/pip" install --upgrade pip
"${DEPLOY_DIR}/.venv/bin/pip" install -r "${DEPLOY_DIR}/requirements.txt"

echo "==> .env from .env.example (manual edit required after)"
if [ ! -f "${DEPLOY_DIR}/.env" ]; then
    cp "${DEPLOY_DIR}/.env.example" "${DEPLOY_DIR}/.env"
    echo "    EDIT ${DEPLOY_DIR}/.env to fill in real values"
fi

echo "==> systemd service"
cp "${DEPLOY_DIR}/deploy/bidding.service" /etc/systemd/system/bidding.service
sed -i "s|/opt/bidding|${DEPLOY_DIR}|g" /etc/systemd/system/bidding.service
sed -i "s|User=ubuntu|User=${SERVICE_USER}|g" /etc/systemd/system/bidding.service
touch /var/log/bidding.log
chown "${SERVICE_USER}:${SERVICE_USER}" /var/log/bidding.log
systemctl daemon-reload
systemctl enable bidding
systemctl start bidding
sleep 3
systemctl status bidding --no-pager || true

echo "==> nginx reverse proxy"
cp "${DEPLOY_DIR}/deploy/nginx.bidding.conf" /etc/nginx/sites-available/bidding
sed -i "s|bidding.mncapro.com|${DOMAIN}|g" /etc/nginx/sites-available/bidding
ln -sf /etc/nginx/sites-available/bidding /etc/nginx/sites-enabled/bidding
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> Let's Encrypt SSL (interactive — confirm email + agree to ToS)"
echo "    Run after DNS A record points ${DOMAIN} → this VM's public IP:"
echo "      sudo certbot --nginx -d ${DOMAIN}"

echo ""
echo "✓ Setup complete. Next steps:"
echo "  1. Edit ${DEPLOY_DIR}/.env (SMTP creds, recipients, DECIDE_TOKEN_SECRET, DASHBOARD_URL=https://${DOMAIN}/)"
echo "  2. Restart service: sudo systemctl restart bidding"
echo "  3. Set DNS A record ${DOMAIN} → $(curl -s ifconfig.me)"
echo "  4. After DNS propagates: sudo certbot --nginx -d ${DOMAIN}"
echo "  5. Trigger first sync: curl -X POST https://${DOMAIN}/sync"
echo "  6. Check logs: tail -f /var/log/bidding.log"
