# Deploying grc-rag to Azure Container Apps

The container serves the FastAPI boundary (`POST /ask`) with the retrieval models and the committed
index baked in. See [ADR-0020](../docs/adr/0020-container-deploy-pluggable-generator.md) for why the
generator is config-selected and what the committed scorecard does — and does not — cover.

> **Read this before quoting numbers.** The published faithfulness figure (0.924) was measured with
> the **local Ollama generator**. This deployment runs hosted Claude. Retrieval metrics carry over;
> faithfulness does not, until the harness is re-run against `GRC_RAG_LLM=anthropic` and a second
> scorecard is committed.

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az --version` ≥ 2.60)
- An Azure subscription, and an `ANTHROPIC_API_KEY`

```bash
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

## 1. Variables

```bash
export RG=grc-rag-rg
export LOC=australiaeast          # Sydney — closest region to Brisbane
export ACR=grcragacr$RANDOM       # must be globally unique, lowercase alphanumeric
export ENVIRONMENT=grc-rag-env
export APP=grc-rag
export IMAGE=grc-rag:0.1.0
```

## 2. Resource group and registry

```bash
az group create --name "$RG" --location "$LOC"

az acr create --resource-group "$RG" --name "$ACR" --sku Basic --admin-enabled true
```

## 3. Build the image in ACR

Building remotely avoids a slow local cross-architecture build — Container Apps runs `linux/amd64`
and an Apple Silicon laptop does not.

```bash
az acr build --registry "$ACR" --image "$IMAGE" --file Dockerfile .
```

Expect this to take several minutes: the layer that pre-caches the two MiniLM models is ~90 MB.

## 4. Container Apps environment

```bash
az containerapp env create \
  --name "$ENVIRONMENT" --resource-group "$RG" --location "$LOC"
```

## 5. Deploy

The API key goes in as a **secret** and is referenced by the env var — never baked into the image
and never passed as a plain `--env-vars` value.

```bash
ACR_SERVER=$(az acr show --name "$ACR" --query loginServer -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR" --query "passwords[0].value" -o tsv)

az containerapp create \
  --name "$APP" \
  --resource-group "$RG" \
  --environment "$ENVIRONMENT" \
  --image "$ACR_SERVER/$IMAGE" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR" \
  --registry-password "$ACR_PASSWORD" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 2 \
  --cpu 1.0 --memory 2.0Gi \
  --secrets "anthropic-key=$ANTHROPIC_API_KEY" \
  --env-vars \
      "ANTHROPIC_API_KEY=secretref:anthropic-key" \
      "GRC_RAG_LLM=anthropic" \
      "GRC_RAG_INDEX_DIR=/app/data/processed" \
      "GRC_RAG_CORS_ORIGINS=https://<your-ui-host>"
```

`--min-replicas 0` scales to zero when idle, so a demo costs nothing between visits. The trade-off
is a cold start of roughly 10–20 seconds while the models load into memory. `2.0Gi` is the floor
for holding both MiniLM models plus the index comfortably.

## 6. Get the URL and smoke-test it

```bash
URL=$(az containerapp show --name "$APP" --resource-group "$RG" \
      --query properties.configuration.ingress.fqdn -o tsv)
echo "https://$URL"

# A grounded question — expect refused=false with citations.
curl -sS -X POST "https://$URL/ask" \
  -H 'content-type: application/json' \
  -d '{"question":"What AI practices does the EU AI Act prohibit?"}' | jq

# An out-of-corpus question — expect refused=true and an empty citations array.
# This is the assertion worth showing anyone: it declines rather than inventing.
curl -sS -X POST "https://$URL/ask" \
  -H 'content-type: application/json' \
  -d '{"question":"What is the capital of France?"}' | jq '.refused, .citations'
```

## 7. Redeploy after a change

```bash
az acr build --registry "$ACR" --image "$IMAGE" --file Dockerfile .
az containerapp update --name "$APP" --resource-group "$RG" --image "$ACR_SERVER/$IMAGE"
```

## Teardown

```bash
az group delete --name "$RG" --yes --no-wait
```

## Running the MCP server

The MCP boundary ([ADR-0021](../docs/adr/0021-mcp-boundary.md)) is local and stdio-based — it is not
part of this container.

```bash
pip install -e ".[mcp]"
python -m grc_rag.mcp_server
```

Wire it into an MCP client (for example `.mcp.json` in Claude Code):

```json
{
  "mcpServers": {
    "grc-rag": {
      "command": "python",
      "args": ["-m", "grc_rag.mcp_server"],
      "env": { "GRC_RAG_INDEX_DIR": "data/processed" }
    }
  }
}
```

The assistant then gets one tool, `ask_grc`, which answers from the corpus with clause-level
citations — or refuses.
