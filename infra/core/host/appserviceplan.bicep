@description('The name of the App Service Plan')
param name string

@description('The location into which the resources should be deployed')
param location string = resourceGroup().location

@description('The tags to apply to the resource')
param tags object = {}

@description('The pricing tier for the App Service Plan')
param sku object = {
  name: 'B1'
  capacity: 1
}

@description('Kind of server OS')
param kind string = 'linux'

@description('Whether to reserve the App Service Plan for Linux workers')
param reserved bool = true

resource appServicePlan 'Microsoft.Web/serverfarms@2022-03-01' = {
  name: name
  location: location
  tags: tags
  sku: sku
  kind: kind
  properties: {
    reserved: reserved
  }
}

output id string = appServicePlan.id
output name string = appServicePlan.name
