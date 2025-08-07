# Azure deployment configuration for Mental Health Chatbot
targetScope = 'resourceGroup'

@minLength(1)
@maxLength(64)
@description('Name of the the environment which is used to generate a short unique hash used in all resources.')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Id of the user or app to assign application roles')
param principalId string = ''

// Optional parameters to override the default Azure resource names
param appServicePlanName string = ''
param backendServiceName string = ''
param resourceGroupName string = ''
param storageAccountName string = ''
param keyVaultName string = ''

@description('Flag to use Azure OpenAI account for mental health responses')
param useAzureOpenAI bool = false

var abbrs = loadJsonContent('abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

// Organize resources in a resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: !empty(resourceGroupName) ? resourceGroupName : '${abbrs.resourcesResourceGroups}${environmentName}'
}

// Create App Service Plan for hosting the Flask app
module appServicePlan 'core/host/appserviceplan.bicep' = {
  name: 'appserviceplan'
  scope: rg
  params: {
    name: !empty(appServicePlanName) ? appServicePlanName : '${abbrs.webServerFarms}${resourceToken}'
    location: location
    tags: tags
    sku: {
      name: 'B1'
      capacity: 1
    }
    kind: 'linux'
    reserved: true
  }
}

// Storage account for SQLite database and session storage
module storage 'core/storage/storage-account.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    name: !empty(storageAccountName) ? storageAccountName : '${abbrs.storageStorageAccounts}${resourceToken}'
    location: location
    tags: tags
    publicNetworkAccess: 'Enabled'
    sku: {
      name: 'Standard_LRS'
    }
    deleteRetentionPolicy: {
      enabled: true
      days: 2
    }
  }
}

// Key Vault for storing sensitive configuration
module keyVault 'core/security/keyvault.bicep' = {
  name: 'keyvault'
  scope: rg
  params: {
    name: !empty(keyVaultName) ? keyVaultName : '${abbrs.keyVaultVaults}${resourceToken}'
    location: location
    tags: tags
    principalId: principalId
  }
}

// The Flask web application
module backend 'core/host/appservice.bicep' = {
  name: 'web'
  scope: rg
  params: {
    name: !empty(backendServiceName) ? backendServiceName : '${abbrs.webSitesAppService}backend-${resourceToken}'
    location: location
    tags: union(tags, { 'azd-service-name': 'backend' })
    appServicePlanId: appServicePlan.outputs.id
    runtimeName: 'python'
    runtimeVersion: '3.11'
    scmDoBuildDuringDeployment: true
    managedIdentity: true
    storageAccountName: storage.outputs.name
    keyVaultName: keyVault.outputs.name
    appSettings: {
      FLASK_ENV: 'production'
      FLASK_DEBUG: 'False'
      SECRET_KEY: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=secret-key)'
      GOOGLE_API_KEY: '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=google-api-key)'
      DATABASE_URL: 'sqlite:///mentalhealth.db'
      PYTHONPATH: '/home/site/wwwroot'
      WEBSITES_PORT: '5000'
    }
  }
}

// App outputs
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output BACKEND_URI string = backend.outputs.uri
output APPLICATIONINSIGHTS_CONNECTION_STRING string = backend.outputs.applicationInsightsConnectionString
