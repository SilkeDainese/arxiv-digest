#!/usr/bin/env bash
# One-time GCP setup for arxiv-digest Workload Identity Federation
# Run this once from your local machine: bash gcp-wif-setup.sh
# Make executable with: chmod +x gcp-wif-setup.sh
set -euo pipefail

PROJECT_ID="silke-hub"
PROJECT_NUMBER="932510967521"
GITHUB_REPO="SilkeDainese/arxiv-digest"
POOL_NAME="github-pool"
PROVIDER_NAME="github-provider"
SA_NAME="arxiv-digest-runner"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Setting up WIF for $GITHUB_REPO → $PROJECT_ID"

# 1. Enable required APIs
gcloud services enable iamcredentials.googleapis.com \
  iam.googleapis.com \
  aiplatform.googleapis.com \
  --project=$PROJECT_ID

# 2. Create service account
gcloud iam service-accounts create $SA_NAME \
  --project=$PROJECT_ID \
  --display-name="arXiv Digest GitHub Actions Runner"

# 3. Grant Vertex AI User role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user"

# 4. Create Workload Identity Pool
gcloud iam workload-identity-pools create $POOL_NAME \
  --project=$PROJECT_ID \
  --location="global" \
  --display-name="GitHub Actions Pool"

# 5. Create GitHub OIDC provider
gcloud iam workload-identity-pools providers create-oidc $PROVIDER_NAME \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool=$POOL_NAME \
  --display-name="GitHub Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'"

# 6. Bind service account to the pool (allow the specific repo to impersonate)
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/${GITHUB_REPO}"

# 7. Print the values to add to GitHub Actions variables
PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/providers/${PROVIDER_NAME}"
echo ""
echo "Done! Add these to GitHub Actions variables (not secrets — no sensitive data):"
echo "   WIF_PROVIDER  = ${PROVIDER_RESOURCE}"
echo "   WIF_SERVICE_ACCOUNT = ${SA_EMAIL}"
echo ""
echo "Go to: https://github.com/${GITHUB_REPO}/settings/variables/actions"
