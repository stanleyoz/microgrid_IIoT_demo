#!/bin/bash
# deploy_dashboard_vm.sh — run from repo root on your local machine
# Deploys the Streamlit dashboard to the broker VM and configures Nginx.
#
# Usage:
#   ./scripts/deploy_dashboard_vm.sh
#
# Prerequisites:
#   1. DNS A record for microgrid.tinylab.ai → 34.87.254.184 must already be set and propagated
#   2. gcloud CLI authenticated (gcloud auth list)
#   3. SSH key at edge/id_microgrid_demo

set -euo pipefail

VM_IP="34.87.254.184"
VM_USER="amplifiedengr"
SSH_KEY="edge/id_microgrid_demo"
PROJECT="microgrid-demo"
DOMAIN="microgrid.tinylab.ai"

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

# ── helpers ──────────────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

# ── preflight checks ─────────────────────────────────────────────────────────
info "=== Preflight checks ==="

[ -f "$SSH_KEY" ] || die "SSH key not found: $SSH_KEY  (run from repo root)"
chmod 600 "$SSH_KEY"

if ! gcloud auth print-access-token &>/dev/null; then
    die "Not authenticated with gcloud. Run: gcloud auth login"
fi

info "SSH key: OK"
info "gcloud auth: OK"

# ── DNS check ────────────────────────────────────────────────────────────────
info "=== Checking DNS resolution for $DOMAIN ==="
RESOLVED=$(dig +short "$DOMAIN" | head -1 || true)
if [ "$RESOLVED" = "$VM_IP" ]; then
    info "DNS: $DOMAIN → $RESOLVED  ✓"
else
    warn "DNS: $DOMAIN resolves to '$RESOLVED', expected $VM_IP"
    warn "If DNS is not yet propagated, certbot (TLS) will fail."
    read -rp "Continue anyway? [y/N] " ans
    [[ "${ans,,}" == "y" ]] || exit 0
fi

# ── GCP firewall ─────────────────────────────────────────────────────────────
info "=== GCP firewall: ensure ports 80 and 443 are open ==="

# Detect the VM's network tags
VM_TAGS=$(gcloud compute instances describe microgrid-broker \
    --project="$PROJECT" \
    --zone=australia-southeast1-a \
    --format="value(tags.items)" 2>/dev/null || echo "")

info "VM network tags: ${VM_TAGS:-<none>}"

# Check if the rule already exists
if gcloud compute firewall-rules describe allow-http-https \
    --project="$PROJECT" &>/dev/null; then
    info "Firewall rule allow-http-https: already exists"
else
    if [ -n "$VM_TAGS" ]; then
        TARGET_FLAG="--target-tags=$(echo "$VM_TAGS" | tr ';' ',')"
    else
        TARGET_FLAG="--target-tags=microgrid-broker"
        warn "No tags found on VM; applying rule with tag 'microgrid-broker' — verify in console"
    fi

    gcloud compute firewall-rules create allow-http-https \
        --project="$PROJECT" \
        --network=default \
        --allow=tcp:80,tcp:443 \
        $TARGET_FLAG \
        --description="Allow HTTP/HTTPS for Streamlit dashboard"
    info "Firewall rule created"
fi

# ── Verify BigQuery access on service account ────────────────────────────────
info "=== Checking service account BigQuery permissions ==="
SA_ROLES=$(gcloud projects get-iam-policy "$PROJECT" \
    --flatten="bindings[].members" \
    --filter="bindings.members:microgrid-agent" \
    --format="value(bindings.role)" 2>/dev/null || echo "")

if echo "$SA_ROLES" | grep -q "bigquery.dataViewer\|bigquery.admin"; then
    info "BigQuery dataViewer: OK"
else
    warn "roles/bigquery.dataViewer not found on microgrid-agent — granting now"
    gcloud projects add-iam-policy-binding "$PROJECT" \
        --member="serviceAccount:microgrid-agent@${PROJECT}.iam.gserviceaccount.com" \
        --role="roles/bigquery.dataViewer"
fi

# ── SCP files to VM ──────────────────────────────────────────────────────────
info "=== Copying files to VM ==="
scp $SSH_OPTS \
    scripts/nginx-microgrid.conf \
    scripts/microgrid-dashboard.service \
    scripts/vm_setup_dashboard.sh \
    "${VM_USER}@${VM_IP}:/tmp/"

scp $SSH_OPTS \
    scripts/microgrid-dashboard.service \
    "${VM_USER}@${VM_IP}:/tmp/microgrid-dashboard.service"

# Also copy the systemd unit to /etc/systemd/system via sudo on the VM
ssh $SSH_OPTS "${VM_USER}@${VM_IP}" \
    "sudo cp /tmp/microgrid-dashboard.service /etc/systemd/system/microgrid-dashboard.service"

info "Files copied"

# ── Run VM setup script ───────────────────────────────────────────────────────
info "=== Running VM setup script ==="
ssh $SSH_OPTS "${VM_USER}@${VM_IP}" "bash /tmp/vm_setup_dashboard.sh"

# ── Post-setup instructions ───────────────────────────────────────────────────
echo ""
echo "================================================================"
echo " DEPLOYMENT COMPLETE — manual step remaining:"
echo ""
echo " SSH into the VM and run certbot to issue the TLS certificate:"
echo ""
echo "   ssh -i edge/id_microgrid_demo ${VM_USER}@${VM_IP}"
echo "   sudo certbot --nginx -d ${DOMAIN}"
echo "   sudo systemctl reload nginx"
echo ""
echo " Then verify from outside:"
echo "   curl -I https://${DOMAIN}"
echo "   # Expect: HTTP/2 200 from Streamlit"
echo ""
echo " Dashboard URL:  https://${DOMAIN}"
echo "================================================================"
