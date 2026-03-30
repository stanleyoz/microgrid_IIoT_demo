#!/bin/bash
# spinup_notebook.sh — recreate the Vertex AI Workbench instance for model retraining
#
# Usage (run from project root or ml/ directory):
#   ./ml/spinup_notebook.sh                          # uses default anomaly_detection_poc.ipynb
#   ./ml/spinup_notebook.sh my_other_notebook.ipynb  # specify a different notebook file
#
# What it does:
#   1. Stages your local .ipynb to GCS
#   2. Creates a fresh Workbench instance with the same settings as the original
#   3. Waits until ACTIVE, then installs the notebook via startup script
#   4. Prints the JupyterLab URL
#
# When done retraining, tear down with:
#   gcloud workbench instances delete microgrid-anomaly-detection-notebook \
#     --location=australia-southeast1-a --project=microgrid-demo --quiet

set -e

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT=microgrid-demo
ZONE=australia-southeast1-a
INSTANCE=microgrid-anomaly-detection-notebook
SA=microgrid-agent@microgrid-demo.iam.gserviceaccount.com
NOTEBOOK_FILE="${1:-anomaly_detection_poc.ipynb}"
GCS_STAGING=gs://microgrid-ml-artefacts/notebooks

# Machine: n1-standard-4 (4 vCPU / 15 GB RAM) — sufficient for sklearn/pandas, no GPU needed
# Upgrade to n1-standard-8 if training on >500k rows becomes slow
MACHINE_TYPE=n1-standard-4
DISK_GB=100
DISK_TYPE=PD_STANDARD

# ── Preflight ─────────────────────────────────────────────────────────────────
echo "================================================================"
echo " Microgrid — Notebook Spinup"
echo " Instance : $INSTANCE"
echo " Zone     : $ZONE"
echo " Machine  : $MACHINE_TYPE  (4 vCPU / 15 GB)"
echo " Notebook : $NOTEBOOK_FILE"
echo "================================================================"
echo ""

# Check for existing instance
EXISTING=$(gcloud workbench instances list \
  --location="$ZONE" --project="$PROJECT" \
  --filter="name=$INSTANCE" --format="value(name)" 2>/dev/null)
if [[ -n "$EXISTING" ]]; then
  echo "ERROR: Instance '$INSTANCE' already exists (state may be ACTIVE or STOPPED)."
  echo "Check: gcloud workbench instances describe $INSTANCE --location=$ZONE --project=$PROJECT --format='value(state)'"
  echo "Delete first with: gcloud workbench instances delete $INSTANCE --location=$ZONE --project=$PROJECT --quiet"
  exit 1
fi

# ── Stage notebook in GCS ─────────────────────────────────────────────────────
if [[ -f "$NOTEBOOK_FILE" ]]; then
  echo "Staging $NOTEBOOK_FILE → $GCS_STAGING/ ..."
  gsutil cp "$NOTEBOOK_FILE" "$GCS_STAGING/$NOTEBOOK_FILE"
  echo "Staged OK."
  STARTUP_SCRIPT="#!/bin/bash
gsutil cp $GCS_STAGING/$NOTEBOOK_FILE /home/jupyter/$NOTEBOOK_FILE
chown jupyter:jupyter /home/jupyter/$NOTEBOOK_FILE
echo 'Notebook installed at /home/jupyter/$NOTEBOOK_FILE'"
else
  echo "WARNING: '$NOTEBOOK_FILE' not found in current directory."
  echo "         Instance will be created without a pre-loaded notebook."
  echo "         You can upload manually via JupyterLab → Upload button."
  STARTUP_SCRIPT="#!/bin/bash
echo 'No notebook staged — upload via JupyterLab UI'"
fi
echo ""

# ── Create instance ───────────────────────────────────────────────────────────
echo "Creating Workbench instance (this takes ~3-4 minutes)..."
gcloud workbench instances create "$INSTANCE" \
  --location="$ZONE" \
  --project="$PROJECT" \
  --gce-setup-machine-type="$MACHINE_TYPE" \
  --gce-setup-boot-disk-size-gb="$DISK_GB" \
  --gce-setup-boot-disk-type="$DISK_TYPE" \
  --gce-setup-service-account="$SA" \
  --gce-setup-metadata="startup-script=$STARTUP_SCRIPT"

# ── Wait for ACTIVE ───────────────────────────────────────────────────────────
echo ""
echo -n "Waiting for ACTIVE"
while true; do
  STATE=$(gcloud workbench instances describe "$INSTANCE" \
    --location="$ZONE" --project="$PROJECT" \
    --format="value(state)" 2>/dev/null)
  if [[ "$STATE" == "ACTIVE" ]]; then
    echo " done."
    break
  fi
  echo -n "."
  sleep 15
done

# ── Get JupyterLab URL ────────────────────────────────────────────────────────
PROXY_URL=$(gcloud workbench instances describe "$INSTANCE" \
  --location="$ZONE" --project="$PROJECT" \
  --format="value(proxyUri)" 2>/dev/null)

echo ""
echo "================================================================"
echo " Notebook READY"
if [[ -n "$PROXY_URL" ]]; then
  echo " Open: https://$PROXY_URL"
else
  echo " Open: GCP Console → Vertex AI → Workbench → OPEN JUPYTERLAB"
fi
echo ""
echo " Your notebook: $NOTEBOOK_FILE (in /home/jupyter/)"
echo " ML artefacts:  gs://microgrid-ml-artefacts/models/"
echo ""
echo " When done retraining, save and then tear down:"
echo "   gcloud workbench instances delete $INSTANCE \\"
echo "     --location=$ZONE --project=$PROJECT --quiet"
echo "================================================================"
