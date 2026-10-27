#!/usr/bin/env bash
# One-time Google Cloud setup for deploying ThreadSmith. Idempotent: safe to re-run.
#
# Reads GOOGLE_CLOUD_PROJECT, GCS_BUCKET_NAME and BUFFER_API_KEY from
# backend/thread_smith/.env and acts as whichever account gcloud is logged in as.
# Set PERSONAL_EMAIL=you@example.com in front of the command to grant the user
# roles to a different account.
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE="backend/thread_smith/.env"
REGION="us-central1"
SA_NAME="threadsmith-frontend"
SECRET_NAME="buffer-api-key"

# A service-account key in GOOGLE_APPLICATION_CREDENTIALS overrides your own
# login and is the usual cause of 403s on this project.
unset GOOGLE_APPLICATION_CREDENTIALS

step() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Read KEY=value from .env without sourcing it (nothing in it gets executed).
env_value() {
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- \
    | sed -e 's/^["'\'']//' -e 's/["'\'']$//' -e 's/[[:space:]]*$//'
}

[ -f "$ENV_FILE" ] || die "$ENV_FILE not found. Copy .env.example there and fill it in."

PROJECT_ID="$(env_value GOOGLE_CLOUD_PROJECT)"
BUCKET="$(env_value GCS_BUCKET_NAME)"
[ -n "$PROJECT_ID" ] || die "GOOGLE_CLOUD_PROJECT is not set in $ENV_FILE."

# ---------------------------------------------------------------- login ----
step "Checking login"
ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
[ -n "$ACCOUNT" ] || die "gcloud is not logged in. Run: gcloud auth login"
MEMBER_EMAIL="${PERSONAL_EMAIL:-$ACCOUNT}"
echo "gcloud account: $ACCOUNT"
echo "Granting user roles to: $MEMBER_EMAIL"
echo "Project: $PROJECT_ID"

gcloud config set project "$PROJECT_ID" --quiet >/dev/null

if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo "No Application Default Credentials yet; opening the browser to log in."
  gcloud auth application-default login
fi
gcloud auth application-default set-quota-project "$PROJECT_ID" --quiet >/dev/null 2>&1 \
  || echo "WARNING: could not set the ADC quota project (needs serviceusage.services.use)."

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

# ----------------------------------------------------------------- APIs ----
step "Enabling APIs (takes a minute the first time)"
gcloud services enable \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  cloudresourcemanager.googleapis.com \
  storage.googleapis.com \
  --project "$PROJECT_ID"

# --------------------------------------------------------------- bucket ----
if [ -n "$BUCKET" ]; then
  step "Bucket gs://$BUCKET"
  if gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "Already exists."
  else
    gcloud storage buckets create "gs://$BUCKET" \
      --project "$PROJECT_ID" \
      --location "$REGION" \
      --uniform-bucket-level-access \
      --public-access-prevention
  fi
else
  step "Skipping bucket: GCS_BUCKET_NAME is not set in $ENV_FILE"
fi

# ----------------------------------------------------------- your roles ----
step "Granting roles/aiplatform.user to $MEMBER_EMAIL"
case "$MEMBER_EMAIL" in
  *.gserviceaccount.com) MEMBER="serviceAccount:$MEMBER_EMAIL" ;;
  *) MEMBER="user:$MEMBER_EMAIL" ;;
esac
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "$MEMBER" --role roles/aiplatform.user \
  --condition None --quiet >/dev/null

# ------------------------------------------------ frontend service account ----
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
step "Service account $SA_EMAIL"
if gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "Already exists."
else
  gcloud iam service-accounts create "$SA_NAME" \
    --project "$PROJECT_ID" \
    --display-name "ThreadSmith frontend (Cloud Run)"
  # New service accounts take a few seconds to become visible to IAM.
  sleep 10
fi
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$SA_EMAIL" --role roles/aiplatform.user \
  --condition None --quiet >/dev/null

# ------------------------------------------------- Agent Identity principal ----
# Your agent's own identity only exists after its first deploy, so grant every
# Agent Identity in this project. The trust domain is per organization, or per
# project when the project has no organization.
ORG_ID="$(gcloud projects get-ancestors "$PROJECT_ID" --format='value(id,type)' 2>/dev/null \
  | awk '$2=="organization"{print $1}')"
if [ -n "$ORG_ID" ]; then
  TRUST_DOMAIN="agents.global.org-$ORG_ID.system.id.goog"
else
  TRUST_DOMAIN="agents.global.project-$PROJECT_NUMBER.system.id.goog"
fi
AGENTS="principalSet://$TRUST_DOMAIN/attribute.platformContainer/aiplatform/projects/$PROJECT_NUMBER"

# ---------------------------------------------------------- Buffer secret ----
if grep -qE '^BUFFER_API_KEY=.+' "$ENV_FILE"; then
  step "Secret $SECRET_NAME"
  if ! gcloud secrets describe "$SECRET_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets create "$SECRET_NAME" --project "$PROJECT_ID" \
      --replication-policy automatic >/dev/null
    echo "Created."
  fi
  # Piped straight from .env so the key never appears in your shell history.
  NEW_KEY="$(env_value BUFFER_API_KEY)"
  CURRENT_KEY="$(gcloud secrets versions access latest --secret "$SECRET_NAME" \
    --project "$PROJECT_ID" 2>/dev/null || true)"
  if [ "$NEW_KEY" = "$CURRENT_KEY" ]; then
    echo "Latest version already matches .env."
  else
    printf '%s' "$NEW_KEY" | gcloud secrets versions add "$SECRET_NAME" \
      --project "$PROJECT_ID" --data-file=- >/dev/null
    echo "Stored a new version from .env."
  fi
  unset NEW_KEY CURRENT_KEY

  step "Letting the deployed agent read $SECRET_NAME"
  gcloud secrets add-iam-policy-binding "$SECRET_NAME" --project "$PROJECT_ID" \
    --member "$AGENTS" --role roles/secretmanager.secretAccessor \
    --condition None --quiet >/dev/null
else
  step "Skipping secret: BUFFER_API_KEY is not set in $ENV_FILE"
fi

# ------------------------------------------------- agent access to bucket ----
if [ -n "$BUCKET" ]; then
  step "Letting the deployed agent write to gs://$BUCKET"
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member "$AGENTS" --role roles/storage.objectAdmin --quiet >/dev/null
fi

step "Done"
cat <<EOF
Project:          $PROJECT_ID ($PROJECT_NUMBER)
Your roles:       roles/aiplatform.user -> $MEMBER_EMAIL
Frontend SA:      $SA_EMAIL
Agent identities: $AGENTS
Secret:           $SECRET_NAME (set BUFFER_API_KEY_SECRET=$SECRET_NAME for the deployed agent)
Bucket:           ${BUCKET:-<none>}
EOF
