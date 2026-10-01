# RiverKin — one-time Azure setup

Run these in **Azure Cloud Shell (Bash)** at https://shell.azure.com to avoid Windows quoting issues.
Do it once. After this, every push to `main` deploys automatically.

Order matters: scaffold both repos with Claude Code first so each has a working `Dockerfile`,
then run steps 1–7. Check any command with `--help` if the CLI version complains.

## 0. Variables (edit the unique names)
```bash
RG=rg-riverkin
LOC=westeurope            # or centralindia; use a region your subscription allows
SUFFIX=rk$RANDOM          # makes global names unique; write the value down
ACR=riverkinacr$SUFFIX
CAE=cae-riverkin
KV=kv-riverkin-$SUFFIX
PG=pg-riverkin-$SUFFIX
SA=striverkin$SUFFIX
API=ca-riverkin-api
WEB=ca-riverkin-web
FHIR=ca-riverkin-fhir
JOB=caj-riverkin-scheduler
GH_USER=Aakashdeep-Srivastava
PG_PASS='<generate-a-long-random-password>'
```

## 1. Core resources
```bash
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az group create -n $RG -l $LOC
az acr create -n $ACR -g $RG --sku Basic
az containerapp env create -n $CAE -g $RG -l $LOC
```

## 2. PostgreSQL with PostGIS
```bash
az postgres flexible-server create -n $PG -g $RG -l $LOC \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
  --admin-user rkadmin --admin-password "$PG_PASS" --public-access 0.0.0.0
az postgres flexible-server parameter set -g $RG -s $PG -n azure.extensions -v POSTGIS
az postgres flexible-server db create -g $RG -s $PG -d riverkin
```
`--public-access 0.0.0.0` allows Azure services only. The first Alembic migration runs `CREATE EXTENSION postgis`.

## 3. Key Vault secrets and photo storage
```bash
az keyvault create -n $KV -g $RG -l $LOC --enable-rbac-authorization true
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee $ME --role "Key Vault Secrets Officer" \
  --scope $(az keyvault show -n $KV --query id -o tsv)
# wait ~1 minute for the role to apply, then:
az keyvault secret set --vault-name $KV -n database-url \
  --value "postgresql+asyncpg://rkadmin:$PG_PASS@$PG.postgres.database.azure.com:5432/riverkin?ssl=require"
az keyvault secret set --vault-name $KV -n jwt-secret --value "$(openssl rand -hex 32)"

az storage account create -n $SA -g $RG -l $LOC --sku Standard_LRS --allow-blob-public-access false
az storage container create --account-name $SA -n photos --auth-mode login
```

## 4. First images (from each repo's folder, or let CI do it later)
```bash
az acr build -r $ACR -t riverkin-api:init https://github.com/$GH_USER/riverkin-api.git
```
The web image needs the API URL, so build it after step 5 creates the API.

## 5. Container apps
```bash
# API (external ingress, 1 replica so migrations run once)
az containerapp create -n $API -g $RG --environment $CAE \
  --image $ACR.azurecr.io/riverkin-api:init --registry-server $ACR.azurecr.io --registry-identity system \
  --target-port 8000 --ingress external --min-replicas 1 --max-replicas 1 --system-assigned
API_URL=https://$(az containerapp show -n $API -g $RG --query properties.configuration.ingress.fqdn -o tsv)

# HAPI FHIR (internal only; other apps reach it at http://ca-riverkin-fhir)
az containerapp create -n $FHIR -g $RG --environment $CAE --image hapiproject/hapi:latest \
  --target-port 8080 --ingress internal --min-replicas 1 --max-replicas 1 --cpu 1 --memory 2Gi

# Web
az acr build -r $ACR -t riverkin-web:init --build-arg NEXT_PUBLIC_API_URL=$API_URL \
  https://github.com/$GH_USER/riverkin-web.git
az containerapp create -n $WEB -g $RG --environment $CAE \
  --image $ACR.azurecr.io/riverkin-web:init --registry-server $ACR.azurecr.io --registry-identity system \
  --target-port 3000 --ingress external --min-replicas 1 --max-replicas 3
WEB_URL=https://$(az containerapp show -n $WEB -g $RG --query properties.configuration.ingress.fqdn -o tsv)
```

## 6. Wire secrets into the API (managed identity, nothing in plain text)
```bash
API_PID=$(az containerapp show -n $API -g $RG --query identity.principalId -o tsv)
az role assignment create --assignee $API_PID --role "Key Vault Secrets User" \
  --scope $(az keyvault show -n $KV --query id -o tsv)
az role assignment create --assignee $API_PID --role "Storage Blob Data Contributor" \
  --scope $(az storage account show -n $SA --query id -o tsv)

az containerapp secret set -n $API -g $RG --secrets \
  "database-url=keyvaultref:https://$KV.vault.azure.net/secrets/database-url,identityref:system" \
  "jwt-secret=keyvaultref:https://$KV.vault.azure.net/secrets/jwt-secret,identityref:system"

az containerapp update -n $API -g $RG --set-env-vars \
  DATABASE_URL=secretref:database-url JWT_SECRET=secretref:jwt-secret \
  STORAGE_ACCOUNT_URL=https://$SA.blob.core.windows.net PHOTO_CONTAINER=photos \
  FHIR_BASE_URL=http://$FHIR/fhir CORS_ORIGINS=$WEB_URL APP_ENV=production VLM_PROVIDER=none
```
Scheduled job (rain pull + need scores every 3 h): ask Claude Code to add `az containerapp job create`
with `--trigger-type Schedule --cron-expression "0 */3 * * *"`, the same image, command
`python -m app.jobs.scheduled`, a system identity, and the same Key Vault secret references.

## 7. GitHub Actions login without passwords (OIDC)
```bash
APP_ID=$(az ad app create --display-name riverkin-github --query appId -o tsv)
az ad sp create --id $APP_ID
az role assignment create --assignee $APP_ID --role Contributor \
  --scope $(az group show -n $RG --query id -o tsv)
for REPO in riverkin-api riverkin-web; do
  az ad app federated-credential create --id $APP_ID --parameters "{
    \"name\": \"$REPO-production\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:$GH_USER/$REPO:environment:production\",
    \"audiences\": [\"api://AzureADTokenExchange\"]}"
done
echo "AZURE_CLIENT_ID=$APP_ID"
echo "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)"
echo "AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv)"
echo "API_URL=$API_URL  WEB_URL=$WEB_URL  ACR_NAME=$ACR"
```

## 8. GitHub settings (both repos → Settings → Environments → New environment `production`)
| Name | Type | riverkin-api | riverkin-web |
| --- | --- | --- | --- |
| `AZURE_CLIENT_ID` | Secret | from step 7 | same |
| `AZURE_TENANT_ID` | Secret | from step 7 | same |
| `AZURE_SUBSCRIPTION_ID` | Secret | from step 7 | same |
| `RESOURCE_GROUP` | Variable | `rg-riverkin` | `rg-riverkin` |
| `ACR_NAME` | Variable | your `$ACR` | your `$ACR` |
| `API_APP` | Variable | `ca-riverkin-api` | — |
| `JOB_APP` | Variable | `caj-riverkin-scheduler` | — |
| `WEB_APP` | Variable | — | `ca-riverkin-web` |
| `API_URL` | Variable | your `$API_URL` | your `$API_URL` |
| `WEB_URL` | Variable | — | your `$WEB_URL` |

Also turn on branch protection for `main` (require the `test` job to pass) and Dependabot alerts.

## Cost and safety notes
- Azure for Students gives credit without a card; check that your region is allowed.
- Keep API and web at min 1 replica during judging (no cold starts). Scale down or delete `rg-riverkin` afterwards.
- Never commit `.env`, connection strings or keys. Rotate the Postgres password if it ever leaks.
