# Azure demo deployment

This is a small, offline-first Container Apps deployment. It creates one
Consumption environment, an internally exposed FastAPI app and a publicly exposed
Streamlit app. Both apps use the same verified Linux AMD64 image. It does not
deploy a language model or configure Foundry orchestration.

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
- Persistent log collection is disabled initially. Application Insights and its
  ingestion controls will be a separate change, after hosting is verified.
- Check remaining student credit, the subscription spending limit and budget
  alerts. Alerts do not automatically stop consumption. Cold starts and session
  loss after scaling to zero are expected tradeoffs of this configuration.

## Preview, then deploy

Install Azure CLI and Bicep, sign in, then substitute the verified public image
reference below. Resource-group creation itself does not provision the apps.

```sh
az provider register --namespace Microsoft.App --wait
az bicep install
az group create --name rg-pl-tactical-demo --location germanywestcentral
az deployment group what-if \
  --resource-group rg-pl-tactical-demo \
  --template-file infra/main.bicep \
  --parameters image=ghcr.io/carroyo03/pl-tactical-ai@sha256:REPLACE_WITH_DIGEST
```

After reviewing the resource changes and the credit budget:

```sh
az deployment group create \
  --resource-group rg-pl-tactical-demo \
  --template-file infra/main.bicep \
  --parameters image=ghcr.io/carroyo03/pl-tactical-ai@sha256:REPLACE_WITH_DIGEST
```

The deployment outputs `studioUrl`. Check the public studio health endpoint,
load all three plays, change language and focus, and exercise both local review
scenarios. The API URL is internal to the Container Apps environment and is not
expected to work from your browser. Check revision health and memory before
declaring the deployment successful. HTTP readiness alone does not verify the UI.

The API uses in-memory DuckDB seeded on startup. State is intentionally disposable;
no authored episodes or changes are persisted by this deployment. Single-replica
operation and single revision mode keep Streamlit session routing simple.

Do not add model credentials to this publicly accessible demo until application
authentication and request/cost controls are implemented. Internal API ingress
does not prevent a visitor from triggering model calls through the public studio.

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
