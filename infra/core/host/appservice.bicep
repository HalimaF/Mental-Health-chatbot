@description('The name of the App Service')
param name string

@description('The location into which the resources should be deployed')
param location string = resourceGroup().location

@description('The tags to apply to the resource')
param tags object = {}

@description('The name of the App Service Plan')
param appServicePlanId string

@description('The runtime name')
param runtimeName string = 'python'

@description('The runtime version')
param runtimeVersion string = '3.11'

@description('Enable SCM build during deployment')
param scmDoBuildDuringDeployment bool = true

@description('Enable managed identity')
param managedIdentity bool = true

@description('Storage account name for file shares')
param storageAccountName string = ''

@description('Key Vault name for secrets')
param keyVaultName string = ''

@description('Application settings')
param appSettings object = {}

resource appService 'Microsoft.Web/sites@2022-03-01' = {
  name: name
  location: location
  tags: tags
  identity: managedIdentity ? {
    type: 'SystemAssigned'
  } : null
  properties: {
    serverFarmId: appServicePlanId
    siteConfig: {
      linuxFxVersion: '${runtimeName}|${runtimeVersion}'
      scmDoBuildDuringDeployment: scmDoBuildDuringDeployment
      ftpsState: 'FtpsOnly'
      minTlsVersion: '1.2'
      appSettings: [for key in items(appSettings): {
        name: key.key
        value: key.value
      }]
    }
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

// Configure App Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-insights'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

output uri string = 'https://${appService.properties.defaultHostName}'
output id string = appService.id
output name string = appService.name
output principalId string = managedIdentity ? appService.identity.principalId : ''
output applicationInsightsConnectionString string = appInsights.properties.ConnectionString
