---
title: HF Agent Finder
emoji: 🔎
colorFrom: yellow
colorTo: blue
sdk: docker
app_port: 7860
base_path: /docs
---

# HF Agent Finder

Agent Finder registry adapter for Hugging Face Skills and Spaces.

This Docker Space runs the latest published `hf-agentfinder` package on Python 3.14 at
container start:

```bash
/home/user/app/start-agentfinder.sh
```

The startup wrapper can run a vendored Meilisearch binary from an attached bucket and load
the generated Hugging Face Skills index before starting the Agent Finder API. If the
Meilisearch bucket or skills index artifact is not mounted, the Space still starts and the
combined primary search still returns Hugging Face Spaces results; indexed Skills results
are added when Meilisearch is available.

Plain deployment sketch:

1. `scripts/vendor-meilisearch.py` downloads a pinned Meilisearch release binary, writes a
   checksum/manifest next to it, and syncs that folder to the configured binary bucket.
2. `scripts/configure-space-runtime.py` creates the configured buckets when needed, attaches
   the Meilisearch binary bucket and skills-index bucket as Space volumes, sets runtime
   variables, and stores `MEILI_MASTER_KEY` as a Space secret.
3. `start-agentfinder.sh` copies the mounted Meilisearch binary locally, verifies its
   checksum from the mounted manifest, starts Meilisearch on `127.0.0.1:7700`, loads the
   mounted `hf-skills.ndjson` artifact into `hf_skills`, then starts the Agent Finder API.

This document is an orientation record. The scripts above are the detailed evidence and
should be read directly for exact command behavior, paths, and failure handling.

Expected runtime variables:

- `AGENTFINDER_MEILI_BIN`, e.g.
  `/mnt/meilisearch/v1.44.0/linux-amd64/meilisearch`
- `AGENTFINDER_MEILI_MANIFEST`, e.g.
  `/mnt/meilisearch/v1.44.0/linux-amd64/manifest.json`
- `AGENTFINDER_SKILLS_ARTIFACT_DIR`, e.g.
  `/mnt/skills-index/latest`
- `AGENTFINDER_MEILI_URL`, default `http://127.0.0.1:7700`
- `AGENTFINDER_MEILI_INDEX`, default `hf_skills`
- `AGENTFINDER_PUBLIC_BASE_URL`, optional canonical public URL used in discovery
  documents, referrals, and generated skill URLs when the runtime reports an internal
  base URL; leave unset/blank by default
- `MEILI_MASTER_KEY`, configured as a Space secret

Useful endpoints:

- `GET /health`
- `GET /.well-known/ai-catalog.json` for Agent Finder / AI Catalog discovery
- `POST /search` for combined indexed Hugging Face Skills and Hugging Face Spaces
- `POST /registries/huggingface/spaces/search` for targeted Hugging Face Spaces search
- `GET /docs`
- `GET /skills/huggingface/{owner}/{space}/SKILL.md`
- `GET /spaces/huggingface/{owner}/{space}/agents.md`

Restarting or rebuilding the Space resolves the latest published `hf-agentfinder` release
from PyPI.

Runtime setup helpers from the repo root:

```bash
uv run scripts/vendor-meilisearch.py
uv run scripts/configure-space-runtime.py --set-secret --generate-secret
```
