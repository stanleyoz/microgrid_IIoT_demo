#!/bin/bash
# check_GCP.sh — snapshot of all running microgrid-demo GCP components

PROJECT=microgrid-demo
REGION=australia-southeast1

echo "================================================================"
echo " MICROGRID DEMO — GCP STATUS CHECK"
echo " Project: $PROJECT  |  Region: $REGION"
echo "================================================================"

echo ""
echo "--- CLOUD RUN SERVICES -----------------------------------------"
gcloud run services list \
  --region $REGION --project $PROJECT \
  --format="table(name,status.latestReadyRevisionName,status.url)"

echo ""
echo "--- PUB/SUB TOPICS ---------------------------------------------"
gcloud pubsub topics list \
  --project $PROJECT \
  --format="table(name)"

echo ""
echo "--- PUB/SUB SUBSCRIPTIONS --------------------------------------"
gcloud pubsub subscriptions list \
  --project $PROJECT \
  --format="table(name,topic,pushConfig.pushEndpoint)"

echo ""
echo "--- COMPUTE VMs ------------------------------------------------"
gcloud compute instances list \
  --project $PROJECT \
  --format="table(name,status,networkInterfaces[0].accessConfigs[0].natIP,machineType)"

echo ""
echo "--- BIGQUERY TABLES --------------------------------------------"
bq ls --project_id $PROJECT microgrid_db

echo ""
echo "--- SECRET MANAGER SECRETS -------------------------------------"
gcloud secrets list \
  --project $PROJECT \
  --format="table(name,createTime)"

echo ""
echo "--- GCS BUCKETS ------------------------------------------------"
gcloud storage buckets list \
  --project $PROJECT \
  --format="table(name,location,storageClass)"

echo ""
echo "--- DASHBOARD VM SERVICE (broker VM) ---------------------------"
ssh -i edge/id_microgrid_demo -o StrictHostKeyChecking=accept-new \
    stanl@34.87.254.184 \
    "sudo systemctl status microgrid-dashboard nginx --no-pager -l 2>/dev/null || echo 'Dashboard service not yet deployed'"

echo ""
echo "================================================================"
echo " Done."
echo "================================================================"
