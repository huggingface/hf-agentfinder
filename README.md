# hf-agentfinder

A small Agent Finder registry adapter for Hugging Face Skills and Spaces.

It exposes Hugging Face discovery as:

- a CLI: `agentfinder spaces search "remove background from image"`
- version introspection: `agentfinder --version`
- a generic Agent Finder registry client: `agentfinder search --registry-url https://registry.example "remove background from image"`
- a primary Agent Finder REST API for indexed Hugging Face Skills: `POST /search`
- a nested Hugging Face Spaces registry: `POST /registries/huggingface/spaces/search`
- generated skill artifacts for Spaces via `GET /skills/huggingface/{owner}/{space}/SKILL.md`

The hosted REST API treats indexed Hugging Face Skills as the primary registry. The nested
Spaces registry preserves the generated `SKILL.md` route that wraps a Space's `agents.md`
instructions.

## Features

### Space Search and Skill Generation

`agentfinder` exposes Hugging Face Spaces semantic search as a nested registry backend at
`/registries/huggingface/spaces/search`. Search requests use the Hub's agent-oriented
semantic search (`agents=true`) and return matching Spaces as Agent Finder catalog entries.
By default, results can include generated `application/ai-skill` artifacts, plus
`application/mcp-server+json` entries for matching Spaces tagged `mcp-server`.

Search responses strictly include only Spaces whose runtime stage is `RUNNING`, so returned
entries are limited to Spaces that are currently ready to serve traffic. The runtime stage
is also surfaced in result metadata as `runtimeStage`.

The generated skill wraps the Space's `agents.md` instructions with the required skill
frontmatter (`name` and `description`) plus source metadata such as the Space ID, Hub URL,
app URL, and original `agents.md` URL. This lets clients discover a relevant Space, fetch
the generated skill, and install or load it using their normal skill flow.

For clients that want raw Space descriptors instead of skills, the nested Spaces search
endpoint can return `application/vnd.huggingface.space+json` entries with inline JSON
metadata.

Requests for `application/mcp-server+json` add `filter=mcp-server` to the downstream Hub
search and return MCP server catalog entries that point at the Space's Gradio MCP endpoint
using HTTP transport. When Hub runtime metadata includes a Space domain, that domain is
used for app and MCP URLs; otherwise the adapter falls back to the standard `.hf.space`
slug convention.

The CLI can also query any Agent Finder-compatible registry by passing `--registry-url`.
The value may be either a registry base URL or the `/search` endpoint. In this mode the CLI
POSTs an Agent Finder `SearchRequest` and renders the returned `SearchResponse` using the
same JSON/table output paths as the Hugging Face Spaces adapter.

### Skills Registry and Referrals

The primary HTTP `POST /search` endpoint searches the Meilisearch-backed
`huggingface/skills` index when `AGENTFINDER_MEILI_URL` is configured. It returns
`application/ai-skill` catalog entries sourced from indexed `SKILL.md` artifacts and groups
section-level index hits into skill-level search results.

When clients request referrals with `query.federation` set to `referrals` or `auto`, the
primary registry includes a referral to the nested Hugging Face Spaces registry. This keeps
the single Space deployment simple while still modeling Spaces as a secondary Agent Finder
registry.

### Challenge Registry Server

`agentfinder challenge serve` runs a deterministic local fixture registry for client
development. It returns mixed Agent Finder result types, including skills, MCP servers, A2A
agents, ai-catalog bundles, registry entries, referrals, empty registries, and nested
registries. Use it to test clients that need to follow registry trees and fetch referenced
artifacts without relying on Hugging Face or Meilisearch services.

`agentfinder challenge search` queries a running challenge registry and defaults to
requesting referrals, making it a convenient CLI path for agents that need to practice
Agent Finder traversal. The generic `agentfinder search --registry-url ...` and
`agentfinder spaces search --registry-url ...` commands also accept `--federation
none|referrals|auto`. When those registry-backed commands are run with `--json`, the CLI
prints the registry's raw `SearchResponse` body so clients can inspect exact `results`,
`referrals`, `mediaType`, `url`, `data`, and `pageToken` fields returned by the server.

### Release Automation

Releases are built through the same quality gates as CI: locked dependency sync, Ruff
format/lint checks, `ty` type checking, and pytest. The package supports the same minimum
Python version as `huggingface_hub` (`>=3.10.0`). The hosted Hugging Face Space deployment
uses Python 3.14 for runtime performance.

Run the release check with:

```bash
./scripts/check-release.sh
```

Optionally assert the expected project version:

```bash
./scripts/check-release.sh 0.1.0
```

Use the **Prepare Release** GitHub Action to prepare a release branch. The workflow can bump
`patch`, `minor`, or `major` from the current `pyproject.toml` version, regenerates
`uv.lock`, runs the release check, pushes `release-vX.Y.Z`, and prints the PR URL in the
workflow summary. After merging the PR, publish by running the
**Release** workflow with the merged version, or by pushing the matching `vX.Y.Z` tag. The
release workflow builds artifacts, publishes them to PyPI using trusted publishing, attaches
the artifacts to the GitHub Release, and restarts the Hugging Face Space when the `HF_TOKEN`
secret is configured.

### Hugging Face Space Deployment

The project includes a reproducible Docker Space definition in `deploy/huggingface-space/`.
It uses the official uv Python image and runs the latest published `hf-agentfinder` package
with `uvx --refresh`, so restarting or rebuilding the Space resolves the newest PyPI
release without committing generated application code to the Space repository. This keeps
the hosted Space lightweight while letting PyPI releases drive runtime updates.

The Space startup wrapper can optionally run a pinned Meilisearch binary from an attached
Hugging Face bucket and ingest a generated Hugging Face Skills index artifact from another
attached bucket. When Meilisearch starts successfully, the wrapper exports the configured
Meilisearch URL and index for the API process so `POST /search` uses the loaded skills
index. Helper scripts in `scripts/` vendor the pinned Meilisearch binary, create the
configured buckets, attach them as Space volumes, and configure runtime variables without
running unsupervised installer scripts in the Space.

The documentation here is intentionally an orientation record: it states the deployment
idea and points to the artifacts that contain the operational evidence. For details, read
`agentfinder.toml`, `scripts/vendor-meilisearch.py`,
`scripts/configure-space-runtime.py`, and
`deploy/huggingface-space/start-agentfinder.sh`.

## Usage

The examples below use the standalone `agentfinder` command form.

```bash
> agentfinder --version
> agentfinder spaces search "generate image" --limit 5
> agentfinder spaces search "generate image" --kind skill --json
> agentfinder spaces search "generate image" --kind mcp --json
> agentfinder spaces search "generate image" --json
> agentfinder search --registry-url https://registry.example "generate image" --kind skill --json
> agentfinder serve --port 8080
> agentfinder challenge serve --port 8090
> agentfinder challenge search "find tools and registries" --federation referrals --json
```

### Recommended `hf` extension usage

For Hugging Face CLI users, the recommended install path is as an `hf` extension:

```bash
> hf extensions install huggingface/hf-agentfinder
> hf agentfinder --version
> hf agentfinder spaces search "generate image" --limit 5
```

The project still documents examples as `agentfinder ...` because the same CLI is also
available as a standalone Python console script. When installed as an extension, replace
`agentfinder` with `hf agentfinder`.

```bash
> curl -X POST http://localhost:8080/search \
  -H 'content-type: application/json' \
  -d '{"query":{"text":"upload files to a dataset repo","mediaType":"application/ai-skill"},"pageSize":5}'
```

Search the nested Spaces registry:

```bash
> curl -X POST http://localhost:8080/registries/huggingface/spaces/search \
  -H 'content-type: application/json' \
  -d '{"query":{"text":"remove background from image","mediaType":"application/ai-skill"},"pageSize":5}'
```

Search the local challenge registry:

```bash
> curl -X POST http://localhost:8090/search \
  -H 'content-type: application/json' \
  -d '{"query":{"text":"find tools and registries","federation":"referrals"},"pageSize":10}'
```

Fetch a generated skill:

```bash
> curl http://localhost:8080/skills/huggingface/mcp-tools/FLUX.1-Kontext-Dev/SKILL.md
```

To get generic Hugging Face Space descriptors instead of skill wrappers, request:

```json
{"query":{"text":"remove background from image","mediaType":"application/vnd.huggingface.space+json"},"pageSize":5}
```

### HF_TOKEN handling

Nested Spaces registry search requests can forward a request-scoped Hugging Face token for
the downstream Spaces search call. The server checks `X-HF-Authorization: Bearer ...`, then
`Authorization: Bearer ...`, then `HF_TOKEN: ...`; a header token overrides any token
configured when the server starts and is not stored beyond the request.
