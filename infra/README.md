# Azure demo deployment

This is a small, offline-first Container Apps deployment. It creates one
Consumption environment, an internally exposed FastAPI app and a publicly exposed
Streamlit app. Both apps use the same verified Linux AMD64 image. It does not
deploy a language model or configure Foundry orchestration.

## Deployed demo

The demo is hosted in `rg-pl-tactical-demo` in Germany West Central:

- [Broadcast Studio](https://pl-tactical-demo-studio.happyhill-6f6f935b.germanywestcentral.azurecontainerapps.io)
- API: internal ingress only, within the same Container Apps environment.
- Narration: offline mock; no model credentials or paid model requests.
- Image: `ghcr.io/carroyo03/pl-tactical-ai@sha256:27f178ebf898f92abf530f7a642a85bfbc4e63ae352a528a1101319c519f38c4`.

Azure provisioned an Express environment. Sticky-session configuration is omitted
because Express does not support it; the studio is limited to one replica.
Revisit session handling before increasing that limit.

Verified on 2026-10-21: both Azure apps provisioned successfully; the public studio
health endpoint returned `ok`; the studio container retrieved all three episodes
through the internal API, generated English and Spanish commentary with participating
player focus, and exercised critic recovery and fallback. The image passed all 95
offline tests and real server startup checks in GitHub Actions. The application
process runs as UID 10001. A deployed browser visual review and real model quality,
latency and cost evaluation are still pending.

The operational update was also deployed and checked on 2026-10-21. The internal
API requires service authentication, the public studio returns the configured
response protections, and Log Analytics received application outcome and latency
summaries. The monthly resource-group budget is configured at EUR 10 with email
notifications. Notification delivery has not been exercised with actual spend.

## Local verification

```sh
docker compose up --build --wait --detach
```

Open `http://localhost:8501`. The studio calls `http://api:8000` inside the Compose
network. Both published ports bind to localhost. If these ports are occupied, use
`API_PORT=18080 STUDIO_PORT=18510 docker compose up --build --wait --detach`.
Stop these containers with `docker compose down` using the same project name
if you supplied `-p` when starting them. No Azure credentials are passed to them.

The Docker build uses an allowlist: source, package metadata and the Streamlit
theme. Local credentials, agent instructions, Git history and generated data are
not copied into the image. Runtime processes use an unprivileged account.

## Publish the image

Push the container and infrastructure files to `main`, then run **Actions →
Publish container → Run workflow**. It builds the image, runs the offline tests
and checks both servers before publishing `ghcr.io/carroyo03/pl-tactical-ai:<commit>`.
It uses GitHub's built-in workflow token; no Azure secrets are needed.

On first publication, check the GHCR package settings and make the package
**public**. A public source repository does not guarantee a public package.
The Azure template intentionally contains no registry credentials.
Use the image digest reported by the registry for reproducible deployments.

## Review access and cost before deployment

- Confirm `az account show` identifies the intended Azure for Students subscription.
- Use a dedicated resource group such as `rg-pl-tactical-demo`; keep the existing
  Foundry group separate. Do not delete the Foundry group to stop the demo.
- Confirm the region is allowed by subscription policy. Germany West Central is
  the initial choice; regional support alone does not establish quota availability.
- Both apps request 0.25 vCPU and 0.5 GiB, with minimum replicas 0 and maximum 1.
  They share the subscription's monthly free Consumption allowances. An open
  Streamlit session may keep resources active; maximum replicas is not a spend cap.
- There is no dedicated compute plan, Azure Container Registry, database server,
  private endpoint, NAT gateway or paid model in this template.
- Log Analytics collects operational summaries with bounded ingestion and
  retention. Request content and credentials are not part of application summaries.
- A monthly budget sends notifications to the configured account contact. The
  budget uses the subscription billing currency and does not stop resources.
- Check remaining student credit, the subscription spending limit and budget
  alerts. Alerts do not automatically stop consumption. Cold starts and session
  loss after scaling to zero are expected tradeoffs of this configuration.

## Preview, then deploy

Install Azure CLI and Bicep, sign in, then substitute the verified public image
reference below. Keep service credentials, operational settings and alert contact
details in a private parameters file. `.deployment-local/` is ignored by Git and
is not included in the container image. The template marks private parameters as
secure. Resource-group creation itself does not provision the apps.

```sh
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az bicep install
az group create --name rg-pl-tactical-demo --location germanywestcentral
az deployment group what-if \
  --resource-group rg-pl-tactical-demo \
  --template-file infra/main.bicep \
  --parameters @.deployment-local/azure.parameters.json \
    image=ghcr.io/carroyo03/pl-tactical-ai@sha256:REPLACE_WITH_DIGEST
```

After reviewing the resource changes and the credit budget:

```sh
az deployment group create \
  --resource-group rg-pl-tactical-demo \
  --template-file infra/main.bicep \
  --parameters @.deployment-local/azure.parameters.json \
    image=ghcr.io/carroyo03/pl-tactical-ai@sha256:REPLACE_WITH_DIGEST
```

The deployment outputs `studioUrl`. Check the public studio health endpoint,
load all three plays, change language and focus, and exercise both local review
scenarios. The API URL is internal to the Container Apps environment and is not
expected to work from your browser. Check revision health and memory before
declaring the deployment successful. HTTP readiness alone does not verify the UI.

The API uses in-memory DuckDB seeded on startup. State is intentionally disposable;
no authored episodes or changes are persisted by this deployment. Single-replica
operation and single revision mode keep Streamlit session routing simple.

The public demo keeps paid model selection explicitly disabled. Enabling a paid
provider requires a separate access and cost review. See the application settings
and Azure resource configuration for deployment-specific operational values.

## Optional Azure OpenAI narration in the studio

The studio can call an Azure OpenAI (Foundry) model deployment with its own
system-assigned managed identity, so no API key is stored. Add these values to the
private parameters file:

```json
"enableAzureOpenAI": { "value": true },
"azureOpenAIEndpoint": { "value": "https://<resource>.openai.azure.com/" },
"azureOpenAIDeployment": { "value": "<deployment name>" }
```

Use the resource's `openai.azure.com` host; the generic `cognitiveservices.azure.com`
host returned `PermissionDenied` in our test. When `enableAzureOpenAI` is true it takes
precedence over Groq, and the studio gets `LLM_PROVIDER=azure` and
`AZURE_OPENAI_AUTH=entra`. Commentary and review scenarios are generated in the studio
process; the API stays offline.

After the first deployment, grant the studio identity access to the model resource
(the template cannot do this because the resource may live in another resource group):

```sh
PRINCIPAL=$(az deployment group show -g rg-pl-tactical-demo -n main \
  --query properties.outputs.studioPrincipalId.value -o tsv)
az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" \
  --scope "$(az cognitiveservices account show -g <model-rg> -n <resource> --query id -o tsv)"
```

Role changes can take several minutes to apply. Every request spends subscription
credit; there is no result cache, concurrency is capped at two requests, and each
request makes at most two model calls of ten seconds each. Keep the monthly budget
alert enabled.

## Provider evaluation

`scripts/evaluate_providers.py` runs 18 synthetic cases (3 plays, 2 languages, 3
styles) per provider and reports first-pass and validated rates, latency percentiles,
provider calls and tokens. Latency is reported separately for each provider and is not
comparable across them. Azure needs `--confirm-spend`, paces requests, and saves a
private report in `.deployment-local/`.

## Optional Groq narration in the studio

Azure OpenAI quota is not available for this project, so the studio can run the
local Groq integration inside its own container. This is a third-party model
service, not a Microsoft service; Azure provides the hosting, networking, secret
storage, monitoring and budget. The Azure OpenAI adapter in the API remains
unvalidated and is not used by this deployment.

Add these values to the private parameters file (never commit them):

```json
"enableGroq": { "value": true },
"groqApiKey": { "value": "<Free plan Groq key>" },
"groqModel": { "value": "openai/gpt-oss-120b" }
```

When `enableGroq` is true the studio receives `LLM_PROVIDER=groq` and the key as a
Container Apps secret. The studio still reads episodes from the internal API, but
commentary and review scenarios are generated inside the studio process; the API
never receives a model key or a deliberately altered draft. Keep the Groq
organization on the Free plan with billing disabled. Bicep cannot require the key
when `enableGroq` is true, so always set both; with an empty key the studio shows
"AI commentary is not configured" and keeps the offline preview.

Operational limits to know before a public link is shared:

- Groq limits are per process (four calls per minute, 100 per day, two calls per
  request, a 20-second window). They reset on restart or scale-to-zero and are not
  an account-wide guard.
- Anyone with the public URL can spend that allowance. When it is exhausted the
  studio shows labelled offline fallback commentary instead of failing.
- To disable model use quickly, redeploy with `enableGroq` set to false.


## Operations

Dependency maintenance currently includes a narrow Pillow compatibility override
while Streamlit retains an older version ceiling. The application regression suite
and Streamlit image rendering were checked with the selected version. Remove the
override once the upstream dependency range supports it.

Open the demo resource group in the Azure portal. The Log Analytics workspace
contains the application summaries; use the individual queries in
[monitoring.kql](monitoring.kql) to inspect outcomes, latency and log volume.
Container Apps metrics provide resource and replica health. Keep operational
values and contact details in the private deployment configuration.

The application includes service-to-service authentication, bounded request
processing, response protections and controlled operational logging. Public
documentation describes these controls at a high level. This is a demo baseline,
not a security certification. Budget and ingestion notifications are not an
instantaneous financial cutoff.

## Stop the dedicated demo

Deleting the dedicated demo resource group removes its Container Apps resources
and stops their future compute consumption. This does not remove the GHCR image
or already incurred charges. Verify the group contents before deleting it:

```sh
az resource list --resource-group rg-pl-tactical-demo --output table
az group delete --name rg-pl-tactical-demo
```

## References

- [Container Apps billing](https://learn.microsoft.com/en-us/azure/container-apps/billing)
- [Container Apps ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview)
- [Session affinity](https://learn.microsoft.com/en-us/azure/container-apps/sticky-sessions)
- [Budget alerts](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)
