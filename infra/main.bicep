targetScope = 'resourceGroup'

@description('Public Linux AMD64 image, preferably pinned to its sha256 digest.')
param image string

@description('Must be allowed by the subscription policy and support Container Apps.')
param location string = 'germanywestcentral'

@minLength(3)
@maxLength(20)
param namePrefix string = 'pl-tactical-demo'

@secure()
@minLength(32)
param serviceToken string

@secure()
param operatingLimits object

@secure()
param budgetAlertEmail string

@description('Budget amount in the billing currency of the Azure subscription.')
param monthlyBudgetAmount int = 10

param budgetStartDate string = utcNow('yyyy-MM-01')

var apiName = '${namePrefix}-api'
var studioName = '${namePrefix}-studio'

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: operatingLimits.logDailyGb
    }
  }
}

resource budget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: '${namePrefix}-budget'
  properties: {
    amount: monthlyBudgetAmount
    category: 'Cost'
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: '${budgetStartDate}T00:00:00Z'
    }
    notifications: {
      approaching: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [budgetAlertEmail]
      }
      reached: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: [budgetAlertEmail]
      }
    }
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

resource api 'Microsoft.App/containerApps@2025-01-01' = {
  name: apiName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'api-service-token'
          value: serviceToken
        }
      ]
      ingress: {
        external: false
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          env: [
            { name: 'API_SERVICE_TOKEN', secretRef: 'api-service-token' }
            { name: 'REQUIRE_API_SERVICE_TOKEN', value: 'true' }
            { name: 'DISABLE_PAID_MODELS', value: 'true' }
            { name: 'STRUCTURED_LOGS', value: 'true' }
            { name: 'API_REQUESTS_PER_MINUTE', value: string(operatingLimits.apiRequestsPerMinute) }
            { name: 'API_MAX_INFLIGHT', value: string(operatingLimits.apiMaxInflight) }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
                scheme: 'HTTP'
              }
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 6
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

resource studio 'Microsoft.App/containerApps@2025-01-01' = {
  name: studioName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'api-service-token'
          value: serviceToken
        }
      ]
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'studio'
          image: image
          command: [
            'python'
            '-m'
            'src.ui.gateway'
          ]
          env: [
            { name: 'API_SERVICE_TOKEN', secretRef: 'api-service-token' }
            { name: 'STUDIO_REQUEST_RATE', value: string(operatingLimits.studioRequestRate) }
            { name: 'STUDIO_CONNECTION_LIMIT', value: string(operatingLimits.studioConnections) }
            { name: 'STUDIO_REQUESTS_PER_MINUTE', value: string(operatingLimits.studioRequestsPerMinute) }
            { name: 'STUDIO_MAX_INFLIGHT', value: string(operatingLimits.studioMaxInflight) }
            {
              name: 'API_BASE_URL'
              value: 'https://${api.properties.configuration.ingress.fqdn}'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/_stcore/health'
                port: 8080
                scheme: 'HTTP'
              }
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 6
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output studioUrl string = 'https://${studio.properties.configuration.ingress.fqdn}'
output apiInternalUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output monitoringWorkspaceId string = workspace.id
