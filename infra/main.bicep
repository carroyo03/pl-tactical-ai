targetScope = 'resourceGroup'

@description('Public Linux AMD64 image, preferably pinned to its sha256 digest.')
param image string

@description('Must be allowed by the subscription policy and support Container Apps.')
param location string = 'germanywestcentral'

@minLength(3)
@maxLength(20)
param namePrefix string = 'pl-tactical-demo'

var apiName = '${namePrefix}-api'
var studioName = '${namePrefix}-studio'

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {}
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
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/goals'
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
      ingress: {
        external: true
        targetPort: 8501
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
            'streamlit'
          ]
          args: [
            'run'
            'src/ui/app.py'
            '--server.address'
            '0.0.0.0'
            '--server.port'
            '8501'
            '--server.headless'
            'true'
          ]
          env: [
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
                port: 8501
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
