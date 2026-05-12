# hf-agentfinder

A small Agent Finder registry adapter for Hugging Face Spaces.

It exposes Hugging Face Spaces semantic search as:

- a CLI: `agentfinder spaces search "remove background from image"`
- an Agent Finder-ish REST API: `POST /search`
- generated skill artifacts for Spaces via `GET /skills/huggingface/{owner}/{space}/SKILL.md`

Search results default to `application/ai-skill` entries. Each result points to a generated
`SKILL.md` route that wraps the Space's `agents.md` instructions.

## Features

### Space Search and Skill Generation

`agentfinder` uses Hugging Face Spaces semantic search as a registry backend. Search
requests use the Hub's agent-oriented semantic search (`agents=true`) and return matching
Spaces as Agent Finder catalog entries. By default, results can include generated
`application/ai-skill` artifacts, plus `application/mcp-server+json` entries for matching
Spaces tagged `mcp-server`.

Search responses strictly include only Spaces whose runtime stage is `RUNNING`, so returned
entries are limited to Spaces that are currently ready to serve traffic. The runtime stage
is also surfaced in result metadata as `runtimeStage`.

The generated skill wraps the Space's `agents.md` instructions with the required skill
frontmatter (`name` and `description`) plus source metadata such as the Space ID, Hub URL,
app URL, and original `agents.md` URL. This lets clients discover a relevant Space, fetch
the generated skill, and install or load it using their normal skill flow.

For clients that want raw Space descriptors instead of skills, the same search endpoint can
return `application/vnd.huggingface.space+json` entries with inline JSON metadata.

Requests for `application/mcp-server+json` add `filter=mcp-server` to the downstream Hub
search and return MCP server catalog entries that point at the Space's Gradio MCP SSE
endpoint.

### Release Automation

Releases are built through the same quality gates as CI: locked dependency sync, Ruff
format/lint checks, `ty` type checking, and pytest. The release check script then builds
both source and wheel distributions, inspects the artifacts, and smoke-installs the wheel
in a clean Python 3.14 virtual environment.

Run the release check with:

```bash
./scripts/check-release.sh
```

Optionally assert the expected project version:

```bash
./scripts/check-release.sh 0.1.0
```

Release Please watches conventional commits on `main`, opens a release PR, bumps
`pyproject.toml`, and maintains `CHANGELOG.md`. Merging that release PR creates a `v*` tag.
The Release Please workflow then builds artifacts, publishes them to PyPI with the
`UV_PUBLISH_TOKEN` GitHub secret, attaches the artifacts to the GitHub Release, and restarts
the Hugging Face Space when the `HF_TOKEN` secret is configured. The tag-based release
workflow remains available for manually pushed `v*` tags.

### Hugging Face Space Deployment

The project includes a reproducible Docker Space definition in `deploy/huggingface-space/`.
It uses the official uv Python image and runs the latest published `hf-agentfinder` package
with `uvx --refresh`, so restarting or rebuilding the Space resolves the newest PyPI
release without committing generated application code to the Space repository.

## Usage

```bash
uv run agentfinder spaces search "generate image" --limit 5
uv run agentfinder spaces search "generate image" --kind skill --json
uv run agentfinder spaces search "generate image" --kind mcp --json
uv run agentfinder spaces search "generate image" --json
uv run agentfinder serve --port 8080
```

```bash
curl -X POST http://localhost:8080/search \
  -H 'content-type: application/json' \
  -d '{"query":{"text":"remove background from image","mediaType":"application/ai-skill"},"pageSize":5}'
```

Fetch a generated skill:

```bash
curl http://localhost:8080/skills/huggingface/mcp-tools/FLUX.1-Kontext-Dev/SKILL.md
```

To get generic Hugging Face Space descriptors instead of skill wrappers, request:

```json
{"query":{"text":"remove background from image","mediaType":"application/vnd.huggingface.space+json"},"pageSize":5}
```

### HF_TOKEN handling

HTTP search requests can forward a request-scoped Hugging Face token for the downstream
Spaces search call. The server checks `X-HF-Authorization: Bearer ...`, then
`Authorization: Bearer ...`, then `HF_TOKEN: ...`; a header token overrides any token
configured when the server starts and is not stored beyond the request.
