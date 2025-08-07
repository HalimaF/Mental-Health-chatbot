# Quick Deploy Script for Mental Health Chatbot
# Run this script to deploy your app to Azure in one command

Write-Host "🚀 Mental Health Chatbot - Azure Deployment" -ForegroundColor Green
Write-Host "======================================"

# Check if Azure CLI is installed
try {
    az version | Out-Null
    Write-Host "✅ Azure CLI found" -ForegroundColor Green
} catch {
    Write-Host "❌ Azure CLI not found. Installing..." -ForegroundColor Red
    winget install Microsoft.AzureCLI
}

# Check if Azure Developer CLI is installed
try {
    azd version | Out-Null
    Write-Host "✅ Azure Developer CLI found" -ForegroundColor Green
} catch {
    Write-Host "❌ Azure Developer CLI not found. Installing..." -ForegroundColor Red
    winget install Microsoft.Azd
}

# Login to Azure
Write-Host "🔐 Logging into Azure..." -ForegroundColor Yellow
az login
azd auth login

# Set environment variables
$env:AZURE_ENV_NAME = Read-Host "Enter environment name (e.g., mental-health-prod)"
$env:AZURE_LOCATION = Read-Host "Enter Azure region (e.g., eastus, westus2)"

# Deploy application
Write-Host "🚀 Deploying to Azure..." -ForegroundColor Yellow
azd up

Write-Host "✅ Deployment complete!" -ForegroundColor Green
Write-Host "Your app is now live and accessible worldwide!" -ForegroundColor Green
Write-Host "Users can install it as a mobile app from any browser." -ForegroundColor Green
