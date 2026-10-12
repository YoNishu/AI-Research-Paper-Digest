<#
.SYNOPSIS
    Single-click deployment of AI Research Paper Digest to Azure.

.DESCRIPTION
    Creates all Azure resources (Resource Group, PostgreSQL, Storage, Azure OpenAI,
    Container Registry, Container App) builds and deploys the Docker container, and
    configures all environment variables.

    Uses Container Apps (not App Service) for compute, managed identity for Storage,
    and supports cross-region PostgreSQL when eastus2 is restricted.

.PARAMETER Location
    Azure region for compute + AI. Default: eastus2

.PARAMETER DbLocation
    Azure region for PostgreSQL. Default: northeurope (many regions restricted)

.PARAMETER ResourceGroup
    Resource group name. Default: rg-paper-digest

.PARAMETER Prefix
    Naming prefix for all resources. Default: paperdigest

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -Location eastus2 -DbLocation canadacentral -Prefix mydigest
#>
param(
    [string]$Location        = "eastus2",
    [string]$DbLocation      = "northeurope",
    [string]$ResourceGroup   = "rg-paper-digest",
    [string]$Prefix          = "paperdigest",
    [string]$OpenAIModel     = "gpt-4o",
    [string]$OpenAIVersion   = "2024-08-06",
    [int]$OpenAICapacity     = 10
)

$ErrorActionPreference = "Stop"

# ---------- Derived names ----------
$PostgresServer  = "$Prefix-db"
$PostgresUser    = "pgadmin"
$PostgresDb      = "paper_digest"
$StorageAccount  = "${Prefix}stor".ToLower() -replace '[^a-z0-9]', ''
$AcrName         = "${Prefix}acr".ToLower() -replace '[^a-z0-9]', ''
$ContainerEnv    = "$Prefix-env"
$ContainerApp    = "$Prefix-app"
$OpenAIName      = "$Prefix-ai"
$DeploymentName  = $OpenAIModel
$BlobContainer   = "paper-pdfs"
$ImageTag        = "${AcrName}.azurecr.io/paper-digest:latest"

# ---------- Generate secure password ----------
$PostgresPassword = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
$PostgresPassword += "Aa1!"  # Ensure complexity requirements

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " AI Research Paper Digest — Azure Deploy" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan
Write-Host "  Compute region:  $Location" -ForegroundColor DarkGray
Write-Host "  Database region: $DbLocation" -ForegroundColor DarkGray
Write-Host ""

# ---------- 1. Resource Group ----------
Write-Host "[1/10] Creating resource group $ResourceGroup..." -ForegroundColor Yellow
az group create --name $ResourceGroup --location $Location --output none

# ---------- 2. PostgreSQL Flexible Server ----------
Write-Host "[2/10] Creating PostgreSQL Flexible Server in $DbLocation..." -ForegroundColor Yellow
$existingDb = az postgres flexible-server show --resource-group $ResourceGroup --name $PostgresServer --query "name" --output tsv 2>$null
if ($existingDb) {
    Write-Host "  PostgreSQL already exists, reusing..." -ForegroundColor DarkGray
} else {
    az postgres flexible-server create `
        --resource-group $ResourceGroup `
        --name $PostgresServer `
        --location $DbLocation `
        --admin-user $PostgresUser `
        --admin-password $PostgresPassword `
        --sku-name Standard_B1ms `
        --tier Burstable `
        --storage-size 32 `
        --version 16 `
        --yes `
        --output none
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: PostgreSQL creation failed in $DbLocation. Try a different region with -DbLocation." -ForegroundColor Red
        exit 1
    }
}

# Allow Azure services
az postgres flexible-server firewall-rule create `
    --resource-group $ResourceGroup `
    --name $PostgresServer `
    --rule-name AllowAzure `
    --start-ip-address 0.0.0.0 `
    --end-ip-address 0.0.0.0 `
    --output none 2>$null

# Create database
az postgres flexible-server db create `
    --resource-group $ResourceGroup `
    --server-name $PostgresServer `
    --database-name $PostgresDb `
    --output none 2>$null

Write-Host "  PostgreSQL: $PostgresServer.postgres.database.azure.com ($DbLocation)" -ForegroundColor DarkGray

# ---------- 3. Storage Account (policy-compliant) ----------
Write-Host "[3/10] Creating Storage Account (managed identity auth)..." -ForegroundColor Yellow
az storage account create `
    --resource-group $ResourceGroup `
    --name $StorageAccount `
    --location $Location `
    --sku Standard_LRS `
    --allow-blob-public-access false `
    --allow-shared-key-access false `
    --output none

# Create blob container using Entra ID auth  
$StorageId = (az storage account show --resource-group $ResourceGroup --name $StorageAccount --query "id" --output tsv)

# Assign current user as Storage Blob Data Contributor so we can create the container
$CurrentUserId = (az ad signed-in-user show --query "id" --output tsv)
az role assignment create `
    --role "Storage Blob Data Contributor" `
    --assignee-object-id $CurrentUserId `
    --assignee-principal-type User `
    --scope $StorageId `
    --output none

# Wait for role propagation
Write-Host "  Waiting for role propagation..." -ForegroundColor DarkGray
Start-Sleep -Seconds 30

az storage container create `
    --name $BlobContainer `
    --account-name $StorageAccount `
    --auth-mode login `
    --output none

# ---------- 4. Azure OpenAI (AI Foundry) ----------
# Check if it already exists (from previous run)
$existingAI = az cognitiveservices account show --resource-group $ResourceGroup --name $OpenAIName --query "name" --output tsv 2>$null
if ($existingAI) {
    Write-Host "[4/10] Azure OpenAI already exists, reusing..." -ForegroundColor Yellow
} else {
    Write-Host "[4/10] Creating Azure OpenAI resource..." -ForegroundColor Yellow
    az cognitiveservices account create `
        --resource-group $ResourceGroup `
        --name $OpenAIName `
        --location $Location `
        --kind OpenAI `
        --sku S0 `
        --output none

    # Deploy model
    Write-Host "  Deploying model $OpenAIModel..." -ForegroundColor DarkGray
    az cognitiveservices account deployment create `
        --resource-group $ResourceGroup `
        --name $OpenAIName `
        --deployment-name $DeploymentName `
        --model-name $OpenAIModel `
        --model-version $OpenAIVersion `
        --model-format OpenAI `
        --sku-capacity $OpenAICapacity `
        --sku-name Standard `
        --output none
}

$OpenAIEndpoint = (az cognitiveservices account show `
    --resource-group $ResourceGroup `
    --name $OpenAIName `
    --query "properties.endpoint" --output tsv)

$OpenAIKey = (az cognitiveservices account keys list `
    --resource-group $ResourceGroup `
    --name $OpenAIName `
    --query "key1" --output tsv)

Write-Host "  Endpoint: $OpenAIEndpoint" -ForegroundColor DarkGray

# ---------- 5. Container Registry ----------
# Check if it already exists
$existingAcr = az acr show --name $AcrName --query "name" --output tsv 2>$null
if ($existingAcr) {
    Write-Host "[5/10] Container Registry already exists, reusing..." -ForegroundColor Yellow
} else {
    Write-Host "[5/10] Creating Container Registry..." -ForegroundColor Yellow
    az acr create `
        --resource-group $ResourceGroup `
        --name $AcrName `
        --sku Basic `
        --admin-enabled true `
        --output none
}

# ---------- 6. Build Docker image ----------
Write-Host "[6/10] Building Docker image in ACR..." -ForegroundColor Yellow
az acr build `
    --registry $AcrName `
    --image paper-digest:latest `
    --file Dockerfile . `
    --output none

# ---------- 7. Container Apps Environment ----------
$existingEnv = az containerapp env show --resource-group $ResourceGroup --name $ContainerEnv --query "name" --output tsv 2>$null
if ($existingEnv) {
    Write-Host "[7/10] Container Apps environment already exists, reusing..." -ForegroundColor Yellow
} else {
    Write-Host "[7/10] Creating Container Apps environment..." -ForegroundColor Yellow
    az containerapp env create `
        --resource-group $ResourceGroup `
        --name $ContainerEnv `
        --location $Location `
        --output none
}

# ---------- 8. Container App ----------
Write-Host "[8/10] Creating Container App..." -ForegroundColor Yellow
$DatabaseUrl = "postgresql+asyncpg://${PostgresUser}:${PostgresPassword}@${PostgresServer}.postgres.database.azure.com:5432/${PostgresDb}?ssl=require"
$AcrPassword = (az acr credential show --name $AcrName --query "passwords[0].value" --output tsv)

az containerapp create `
    --resource-group $ResourceGroup `
    --name $ContainerApp `
    --environment $ContainerEnv `
    --image $ImageTag `
    --registry-server "${AcrName}.azurecr.io" `
    --registry-username $AcrName `
    --registry-password $AcrPassword `
    --target-port 8000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 1 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --env-vars `
        AZURE_OPENAI_ENDPOINT=$OpenAIEndpoint `
        AZURE_OPENAI_API_KEY=$OpenAIKey `
        AZURE_OPENAI_DEPLOYMENT=$DeploymentName `
        DATABASE_URL=$DatabaseUrl `
        AZURE_STORAGE_ACCOUNT_NAME=$StorageAccount `
        AZURE_BLOB_CONTAINER_NAME=$BlobContainer `
    --output none

# ---------- 9. Assign managed identity for blob storage ----------
Write-Host "[9/10] Configuring managed identity for blob storage..." -ForegroundColor Yellow

# Enable system-assigned managed identity
az containerapp identity assign `
    --resource-group $ResourceGroup `
    --name $ContainerApp `
    --system-assigned `
    --output none

# Get the managed identity principal ID
$PrincipalId = (az containerapp identity show `
    --resource-group $ResourceGroup `
    --name $ContainerApp `
    --query "principalId" --output tsv)

# Assign Storage Blob Data Contributor to the container app
az role assignment create `
    --role "Storage Blob Data Contributor" `
    --assignee-object-id $PrincipalId `
    --assignee-principal-type ServicePrincipal `
    --scope $StorageId `
    --output none

Write-Host "  Managed identity assigned for blob access" -ForegroundColor DarkGray

# ---------- 10. Restart to pick up identity ----------
Write-Host "[10/10] Restarting container app..." -ForegroundColor Yellow
# Force a new revision to pick up the identity
az containerapp update `
    --resource-group $ResourceGroup `
    --name $ContainerApp `
    --output none

# ---------- Done ----------
$AppUrl = (az containerapp show --resource-group $ResourceGroup --name $ContainerApp --query "properties.configuration.ingress.fqdn" --output tsv)

Write-Host "`n========================================" -ForegroundColor Green
Write-Host " Deployment Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  App URL:        https://$AppUrl/ui" -ForegroundColor White
Write-Host "  API URL:        https://$AppUrl/docs" -ForegroundColor White
Write-Host "  OpenAI:         $OpenAIEndpoint" -ForegroundColor DarkGray
Write-Host "  PostgreSQL:     $PostgresServer.postgres.database.azure.com ($DbLocation)" -ForegroundColor DarkGray
Write-Host "  Storage:        $StorageAccount (managed identity)" -ForegroundColor DarkGray
Write-Host "  Resource Group: $ResourceGroup" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  The app may take 1-2 minutes to start up." -ForegroundColor Yellow
Write-Host "  The scheduler will poll arXiv feeds every 6 hours." -ForegroundColor Yellow
Write-Host ""
Write-Host "To tear down all resources:" -ForegroundColor DarkGray
Write-Host "  az group delete --name $ResourceGroup --yes --no-wait" -ForegroundColor DarkGray
Write-Host ""

# Open in browser
Start-Process "https://$AppUrl/ui"
