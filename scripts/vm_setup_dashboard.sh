#!/bin/bash
# vm_setup_dashboard.sh — runs ON the broker VM after files are SCP'd
# Invoked by deploy_dashboard_vm.sh via SSH heredoc.
set -euo pipefail

REPO_DIR=/opt/microgrid
VENV="$REPO_DIR/.venv"

echo "=== [1/6] Install system packages ==="
sudo apt-get update -q
sudo apt-get install -y -q nginx certbot python3-certbot-nginx python3-venv python3-pip git

echo "=== [2/6] Clone or update repo ==="
if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    git pull --ff-only
else
    if [ -d "$REPO_DIR" ]; then
        echo "Removing existing non-git directory $REPO_DIR"
        sudo rm -rf "$REPO_DIR"
    fi
    sudo git clone https://github.com/stanleyoz/microgrid_IIoT_demo.git "$REPO_DIR"
    sudo chown -R "$USER:$USER" "$REPO_DIR"
fi

echo "=== [3/6] Python venv + dashboard deps ==="
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REPO_DIR/dashboard/requirements.txt"

# Patch the systemd unit to use the venv's streamlit binary
sudo sed -i "s|/usr/local/bin/streamlit|$VENV/bin/streamlit|g" \
    /etc/systemd/system/microgrid-dashboard.service

echo "=== [4/6] Install systemd unit ==="
sudo sed -i "s/User=.*/User=$USER/" /etc/systemd/system/microgrid-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable microgrid-dashboard
sudo systemctl restart microgrid-dashboard
sleep 3
sudo systemctl status microgrid-dashboard --no-pager

echo "=== [5/6] Install nginx config ==="
sudo cp /tmp/nginx-microgrid.conf /etc/nginx/sites-available/microgrid
# Use HTTP-only block until certbot runs; comment out the SSL server block for now
sudo python3 -c "
import re, sys
path = '/etc/nginx/sites-available/microgrid'
text = open(path).read()
# Comment out the ssl server block lines that reference ssl_ directives so nginx starts cleanly
text = re.sub(r'^(\s*)(ssl_certificate|ssl_certificate_key|include\s+/etc/letsencrypt|ssl_dhparam)',
              r'\1# \2', text, flags=re.MULTILINE)
# Change 'listen 443 ssl' to 'listen 443' temporarily so nginx doesn't need certs
text = text.replace('listen 443 ssl;', 'listen 443;')
open(path, 'w').write(text)
"
# Remove default site if present
sudo rm -f /etc/nginx/sites-enabled/default
# Symlink ours
sudo ln -sf /etc/nginx/sites-available/microgrid /etc/nginx/sites-enabled/microgrid
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

echo "=== [6/6] Verify Streamlit is responding ==="
sleep 2
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501 | grep -q "200\|302"; then
    echo "OK — Streamlit responding on :8501"
else
    echo "WARNING — Streamlit not yet responding; check: sudo journalctl -u microgrid-dashboard -n 50"
fi

echo ""
echo "============================================================"
echo " VM setup complete."
echo " Next step (run manually on VM):"
echo "   sudo certbot --nginx -d microgrid.tinylab.ai"
echo "   sudo systemctl reload nginx"
echo "============================================================"
