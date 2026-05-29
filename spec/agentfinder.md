# Agent Finder Specification

# Federated Discovery and Search for Agents

Version: v0.5 (Draft)   
Status: Proposal   
Date: May 28, 2026

## 1\. Overview

LLMs increasingly rely on external capabilities — MCP tools, A2A agents, skills, and other callable services — to extend their functionality. In this document, we refer to these generically as agents or capabilities.

Agent Finder is a specification that defines how AI artifacts are cataloged, discovered, and searched across federated networks.

This version (v0.5) aligns the discovery framework with the broader ai-catalog standard, shifting towards a media-type-driven approach and mandating standard web protocols (REST) for discovery interfaces to ensure maximum interoperability.

## 2\. Motivation

The prevailing model requires users or developers to explicitly "install" or hardcode each agent before use. As the ecosystem scales to thousands or millions of agents, we need a model where LLMs can discover and invoke agents dynamically, similar to how search engines discover web pages.

Agent descriptions tend to be generic, and most LLMs currently select tools by including all descriptions in the context window — which does not scale. Agent Finder addresses this by moving discovery outside the LLM into a dedicated search service, where richer signals (representative queries, publisher identity, compliance metadata, usage patterns) can be leveraged without consuming context window tokens.

## 3\. Core Design Principles

The Agent Finder protocol is guided by the following core design principles to ensure scalability, interoperability, and ease of adoption:

### 3.1 Search-First Discovery

Rather than requiring users or systems to pre-install agents (analogous to the mobile app store paradigm), Agent Finder promotes a model where agents are discovered dynamically through search. Registries maintain a shared, continuously updated index, making capabilities discoverable the moment they are published.

### 3.2 Scalability Beyond Context Windows

Traditional tool selection relies on injecting all descriptions into the LLM's context window, which does not scale. Agent Finder moves the selection problem outside the LLM into a dedicated search service, leveraging information retrieval techniques to scale to thousands or millions of capabilities without consuming context window tokens.

### 3.3 Artifact Agnostic Envelope

The specification does not define or constrain the internal schema of specific agent types (MCP, A2A, etc.). Instead, it acts as a clean envelope that uses IANA Media Types to identify what an artifact is, delegating the definition of artifact-specific metadata to the respective protocol specifications.

\[\!NOTE\] IANA Registration Status: The media types application/a2a-agent-card+json and application/mcp-server+json used in this specification are de-facto community standards tracking towards formal registration. While well-known path directories (like /.well-known/agent-card.json) are officially registered permanent entries, full media type registrations are pending working group joint submission. During this transition, intermediaries SHOULD NOT reject an artifact solely because its media type is not yet in the IANA registry. This concerns media-type registration status only; it does not relax identity or trust verification, which is governed independently by the trustManifest layer (§5).

### 3.4 Strict Value-or-Reference

To ensure safe parsing and predictable behavior in enterprise environments, a catalog entry must contain exactly one of two mutually exclusive keys for its content delivery:

- `url`: A remote reference to the artifact document.  
- `data`: An embedded JSON object containing the full artifact document.

This rule governs artifact delivery only. All other entry fields — discovery metadata such as `tags`, `capabilities`, and `representativeQueries` — are independent of this choice and may accompany either form.

### 3.5 Universal Baseline for Federation

To guarantee that any system can participate in discovery regardless of its execution stack, an Agent Registry MUST expose a standard HTTP REST search interface. While specialized protocols may be used for execution, discovery requires a universal baseline that any HTTP client can access.

### 3.6 Separation of Concerns

To maintain a clean and implementable standard, the protocol delegates operational details:

- Authentication is Delegated: Agent authentication is handled by the specific artifact protocol, not the discovery layer.  
- Distribution is Infrastructure: Mechanisms for physical delivery (OCI, npm, etc.) are left to backend implementation and are not part of the discovery record.

## 4\. The Data Model

The capability manifest (the file publishers host to advertise their agents) is the central data model. This manifest structure builds upon and extends the schema defined by the ai-catalog specification, introducing specialized discovery attributes (such as domain-anchored URN identifiers, root-level capabilities, and representative queries) to ensure high-performance search and compatibility across the broader agent ecosystem.

### 4.1 The Capability Manifest (ai-catalog.json)

A manifest file hosted at /.well-known/ai-catalog.json lists the available artifacts in its `entries` array. It MAY also include a `collections` array linking to child manifests (§4.6).

{

  "specVersion": "1.0",

  "host": {

    "displayName": "Acme Enterprise AI",

    "identifier": "did:web:acme.com"

  },

  "entries": \[

    {

      "identifier": "urn:ai:acme.com:agent:assistant",

      "displayName": "Corporate Assistant (A2A)",

      "type": "application/a2a-agent-card+json",

      "url": "https://api.acme.com/agents/assistant.json",

      "description": "General-purpose corporate A2A assistant.",

      "representativeQueries": \[

        "help me draft an email to the security working group",

        "summarize my unread messages from Todd"

      \]

    },

    {

      "identifier": "urn:ai:acme.com:server:weather",

      "displayName": "Weather Data Node",

      "type": "application/mcp-server+json",

      "url": "https://api.acme.com/mcp/weather.json",

      "capabilities": \["WeatherTool", "ForecastTool"\],

      "description": "Enterprise weather MCP server for live telemetry.",

      "representativeQueries": \[

        "what is the current wind speed in Chicago",

        "get the 5-day forecast for Seattle"

      \]

    },

    {

      "identifier": "urn:ai:acme.com:plugin:finance-suite",

      "displayName": "Finance Tool Bundle",

      "type": "application/ai-catalog+json",

      "description": "A static nested bundle containing an A2A agent and its required market dataset.",

      "tags": \["finance", "bundle"\],

      "data": {

        "specVersion": "1.0",

        "entries": \[

          {

            "identifier": "urn:ai:acme.com:finance:a2a",

            "displayName": "Finance Trading Agent",

            "type": "application/a2a-agent-card+json",

            "url": "https://api.acme.com/agents/finance-trader.json"

          },

          {

            "identifier": "urn:ai:acme.com:market:2026",

            "displayName": "Market Dataset 2026",

            "type": "application/parquet",

            "url": "https://data.acme.com/market-2026.parquet"

          }

        \]

      }

    },

    {

      "identifier": "urn:ai:acme.com:registry:global",

      "displayName": "Acme Global Agent Registry",

      "type": "application/ai-registry+json",

      "url": "https://registry.acme.com/api/v1/",

      "description": "Dynamic REST API search interface to discover all approved enterprise agents.",

      "tags": \["registry", "search", "dynamic"\],

      "trustManifest": {

        "identity": "spiffe://acme.com/registry/global",

        "identityType": "spiffe",

        "attestations": \[

          {

            "type": "SPIFFE-X509",

            "uri": "https://acme.com/.well-known/spiffe/jwks",

            "mediaType": "application/json"

          },

          {

            "type": "SOC2-Type2",

            "uri": "https://trust.acme.com/reports/soc2.pdf",

            "mediaType": "application/pdf"

          }

        \]

      }

    }

  \],

  "collections": \[

    {

      "displayName": "Engineering Department Catalogs",

      "url": "https://acme.com/catalogs/engineering.json",

      "description": "Sub-catalogs containing CI/CD and internal deployment agents."

    }

  \]

}

### 4.2 Catalog Entry Object

Each object in the entries array MUST contain:

| Field | Type | Description |
| :---- | :---- | :---- |
| identifier | String | Globally unique logical identifier for discovery. MUST use a domain-anchored URN namespace format (urn:ai:\<publisher\>:\<namespace\>:\<agent-name\>) where \<publisher\> is a verifiable domain name. This guarantees cross-network uniqueness, nomenclature stability, and decentralized trust binding. See §4.2.1 for detailed format specifications and architectural rationale. |
| displayName | String | Human-readable name. |
| type | String | Type of the AI artifact. |

Exactly one of the following MUST be present:

| Field | Type | Description |
| :---- | :---- | :---- |
| url | String | URL to retrieve the full artifact. |
| data | Object | The complete artifact document inline. |

Optional fields:

| Field | Type | Description |
| :---- | :---- | :---- |
| description | String | Short description. |
| tags | Array | Keywords for filtering. |
| capabilities | Array | Strings representing specific skills or tools (e.g., \["WeatherTool"\]) to enable fast discovery database filtering without full artifact lookup. |
| representativeQueries | Array | Sample natural-language queries (e.g., \["find me a flight booking agent"\]). Used by registries to build semantic vector embeddings for search ranking. SHOULD contain 2–5 examples. |
| version | String | Version of the artifact. |
| updatedAt | String | ISO 8601 timestamp. |
| metadata | Map | Custom metadata key-value pairs. |
| trustManifest | Object | Verifiable identity and trust metadata. |

#### 4.2.1 Agent Identifier (identifier) Format and Rationale

The identifier field serves as the primary logical handle for an agent or capability across federated discovery networks. It MUST follow a standardized, domain-anchored URN format complying with IETF RFC 8141:

urn:ai:\<publisher\>:\<namespace\>:\<agent-name\>

Format Structure

- urn: Mandatory prefix indicating a Uniform Resource Name.  
- ai: The Namespace Identifier (NID), designating the AI artifact and agent discovery ecosystem.  
- \<publisher\>: The Namespace Specific String (NSS) root. MUST be a fully qualified domain name (FQDN) representing the publisher or host organization (e.g., acme.com, github.com). This domain acts as the organizational trust anchor and MUST be verifiable against the cryptographic workload identity in the trustManifest.  
- \<namespace\>: Optional hierarchical segments separated by : (e.g., finance:trading, weather:telemetry). Allows publishers to categorize capabilities by department, team, or product line without altering infrastructure routing.  
- \<agent-name\>: Mandatory terminal segment representing the specific, logical short name of the agent or tool (e.g., assistant, pptx-creator).

Please see more details at Architectural Rationale for URN Restriction

### 4.3 Host Info Object

Describes the operator of the catalog.

| Field | Type | Description |
| :---- | :---- | :---- |
| displayName | String | Human-readable name of the host. |
| identifier | String | Optional. Verifiable identifier (DID or domain). |
| documentationUrl | String | Optional. URL to documentation. |
| logoUrl | String | Optional. URL to logo. |
| trustManifest | Object | Optional. Trust metadata for the host. |

### 4.4 Examples

The Solo Developer Path

No complex identity ceremony or cloud account required.

An agent hosted on Hugging Face Spaces (MCP), published in a manifest:

{

  "specVersion": "1.0",

  "host": { "displayName": "Alice's AI Tools" },

  "entries": \[

    {

      "identifier": "urn:ai:hf.co:alice-dev:weather-agent",

      "displayName": "Weather Agent",

      "type": "application/mcp-server+json",

      "data": {

        "name": "Weather Agent",

        "description": "Simple weather lookup using open data",

        "tools": \[

          {

            "name": "get\_weather",

            "description": "Get current weather for a city",

            "inputSchema": {

              "type": "object",

              "properties": { "city": { "type": "string" } },

              "required": \["city"\]

            }

          }

        \]

      }

    }

  \]

}

A skill hosted on GitHub, published in a manifest:

{

  "specVersion": "1.0",

  "host": { "displayName": "Alice's AI Tools" },

  "entries": \[

    {

      "identifier": "urn:ai:github.com:alice-dev:pptx-creator",

      "displayName": "pptx-creator",

      "type": "application/ai-skill",

      "url": "https://github.com/alice-dev/pptx-creator",

      "description": "Create professional PowerPoint presentations following brand guidelines."

    }

  \]

}

Discovery via GitHub Pages (combining the above):

{

  "specVersion": "1.0",

  "host": { "displayName": "Alice's AI Tools" },

  "entries": \[

    {

      "identifier": "urn:ai:hf.co:alice-dev:weather-agent",

      "displayName": "Weather Agent",

      "type": "application/mcp-server+json",

      "url": "https://alice-dev.github.io/weather-agent/entry.json"

    },

    {

      "identifier": "urn:ai:github.com:alice-dev:pptx-creator",

      "displayName": "pptx-creator",

      "type": "application/ai-skill+md",

      "url": "https://github.com/alice-dev/pptx-creator"

    }

  \]

}

Enterprise Example

Using trustManifest for compliance, published in a manifest.

{

  "specVersion": "1.0",

  "host": {

    "displayName": "Acme Enterprise AI",

    "identifier": "did:web:acme.com"

  },

  "entries": \[

    {

      "identifier": "urn:ai:acme.com:travel:concierge",

      "displayName": "Travel Concierge",

      "type": "application/a2a-agent-card+json",

      "url": "https://api.acme.com/travel/concierge.json",

      "description": "AI-powered travel planning",

      "trustManifest": {

        "identity": "spiffe://acme.com/travel/concierge",

        "identityType": "spiffe",

        "attestations": \[

          {

            "type": "SPIFFE-X509",

            "uri": "https://acme.com/.well-known/spiffe/jwks",

            "mediaType": "application/json"

          },

          {

            "type": "SOC2-Type2",

            "uri": "https://trust.acme.com/reports/soc2.pdf",

            "mediaType": "application/pdf"

          },

          {

            "type": "GDPR",

            "uri": "https://trust.acme.com/compliance/gdpr",

            "mediaType": "text/html"

          }

        \]

      }

    }

  \]

}

### 4.5 Description Vocabulary

Catalog entries MAY use Schema.org vocabulary (or comparable structured schemas) in their descriptive fields. Any Schema.org-based markup used to describe the agent can be leveraged as filter dimensions in the Search API. This allows domain-specific structured metadata (pricing, geographic coverage, supported languages, certifications) to be attached to records and queried against.

### 4.6 Collections

A manifest MAY include a top-level `collections` array alongside `entries`. Where `entries` describe individual artifacts (leaf capabilities), `collections` are links to other `ai-catalog.json` manifests. They let a publisher compose and delegate — a root manifest can point to departmental or partner sub-catalogs without inlining their contents.

Each object in the `collections` array:

| Field | Type | Description |
| :---- | :---- | :---- |
| url | String | Required. URL of a child ai-catalog.json manifest. |
| displayName | String | Optional. Human-readable name of the collection. |
| description | String | Optional. Short description. |

Registries follow `collections` links during web ingestion (§6.2), crawling child manifests transitively to build their index. Collections are the crawl edges of the static discovery layer.

## 5\. Identity and Trust

Identity binding, compliance attestations, provenance, and cryptographic signatures are consolidated into the optional trustManifest object, as defined in the ai-catalog specification. This keeps the core entry lightweight for simple use cases while providing a robust hook for enterprise compliance, entirely separate from the artifact's native operational metadata.

### 5.1 The Trust Manifest Object

The trustManifest object sits alongside the artifact content in a catalog entry and contains the following key members:

| Field | Type | Description |
| :---- | :---- | :---- |
| identity | String | Required. Globally unique cryptographic workload identifier (e.g., a SPIFFE ID, DID, or HTTPS FQDN URI). Decoupled from the entry's discovery identifier. The cryptographic trust domain inside this identity MUST align with the authority domain root embedded in the discovery identifier namespace. |
| identityType | String | Optional. Type hint for the identity URI (e.g., "did", "spiffe", "https"). |
| attestations | Array | Optional. List of Attestation objects providing verifiable claims. |
| provenance | Array | Optional. List of Provenance Link objects recording lineage. |
| signature | String | Optional. Detached JWS signature computed over the Trust Manifest content. |

### 5.2 Attestation Object

Provides verifiable proof of a claim (e.g., compliance certifications).

| Field | Type | Description |
| :---- | :---- | :---- |
| type | String | Required. Attestation type (e.g., "SOC2-Type2", "HIPAA-Audit"). |
| uri | String | Required. Location of the attestation document. |
| mediaType | String | Required. Format of the document (e.g., "application/pdf"). |
| digest | String | Optional. Cryptographic hash for integrity verification. |

### 5.3 Provenance Link Object

Records lineage and source information.

| Field | Type | Description |
| :---- | :---- | :---- |
| relation | String | Required. Relationship type (e.g., "derivedFrom", "publishedFrom"). |
| sourceId | String | Required. Identifier of the source artifact or data. |
| sourceDigest | String | Optional. Digest of the source for verification. |

For full verification procedures (signature checking, key resolution), refer to the core ai-catalog specification.

## 6\. Discovery

The discovery specification supports two operational layers:

- Static Discovery: A decentralized publishing mechanism where developers and enterprises host static JSON manifests.  
- Dynamic Discovery: Active, searchable services (Registries) that index static catalogs and expose dynamic search endpoints.

### 6.1 Discovery Mechanisms

Publishers advertise their capability manifests via the following mechanisms:

- Well-Known URI: Hosting the manifest at https://{domain}/.well-known/ai-catalog.json.  
- Agentmap Directive: Adding an entry in robots.txt (e.g., Agentmap: [https://example.com/catalog.json](https://example.com/catalog.json)).  
- HTML Link Tag: Including \<link rel="ai-catalog" href="..."\> in the \<head\> of a document.  
- DNS: Publishing Service Binding records in the DNS that point directly to either a static capability manifest (e.g., \_catalog.\_agents.example.com) or a dynamic Agent Registry search endpoint (e.g., \_search.\_agents.example.com).

### 6.2 Ingestion Pipelines

Agent Registry instances populate their indexes through ingestion pipelines:

- Web Ingestion (Required): Crawling ai-catalog.json files from discovered URIs, following `collections` links (§4.6) to child manifests transitively. All Agent Finder implementations MUST support this.  
- Additional Pipelines (Optional): Registries may support scanning git repositories, npm registries, or OCI registries as indicated by their configuration.

## 7\. The Agent Finder API

An Agent Registry MUST expose a standard HTTP REST search interface to guarantee universal federation. The operational base URL for these endpoints is discovered dynamically by identifying catalog entries within the static ai-catalog.json manifest that carry the application/ai-registry+json media type, as defined in §4.1.

### 7.1 The Query Model

The `POST /search` and `POST /explore` endpoints accept a common `query` object with two members, `text` and `filter`. Each endpoint defines its own additional parameters alongside `query` (see §7.2 and §7.3) and its own presence requirements for `text` and `filter`.

{

  "query": {

    "text": "find me a flight booking agent",

    "filter": {

      "type": \["application/a2a-agent-card+json"\],

      "tags": \["finance"\],

      "trustManifest.attestations.type": \["SOC2-Type2"\]

    }

  }

}

| Field | Type | Description |
| :---- | :---- | :---- |
| text | String | Natural-language description of the need. Narrows the result set by semantic relevance. |
| filter | Object | Structured constraints. Keys are field paths into the catalog entry; values are arrays (a bare scalar is accepted as a single-element array). |

`text` and `filter` compose: an entry is in the matched set if it satisfies the relevance criteria for `text` (when present) AND every constraint in `filter` (when present).

Filter semantics. Field paths are dot-separated to address nested fields (e.g. trustManifest.attestations.type). When the value at a path is an array, a constraint matches if any element satisfies it. Within a single key, values are combined with OR; across keys, with AND.

Extensibility. Any attribute present in a catalog entry MAY be used as a filter key — standard fields (type, tags, capabilities, publisher, version, …), nested fields under trustManifest or host, custom metadata.\* fields, and Schema.org-vocabulary fields (§4.5). New attributes become filterable without changes to this specification.

The `publisher` key is derived from the `<publisher>` segment of an entry's URN identifier (§4.2.1), not a stored field; registries extract it from the identifier.

Registry support. Registries SHOULD support filtering on common standard fields; support for metadata.\* and other extension fields is registry-defined. A registry MAY reject a filter that references an unsupported field path with a 400 error.

### 7.2 Search (POST /search)

Accepts a `query` (§7.1) and returns catalog entries ranked by relevance. For Search, `text` is required; `filter` is optional.

Request Schema:

{

  "query": {

    "text": "find me a flight booking agent",

    "filter": {

      "type": \["application/a2a-agent-card+json"\]

    }

  },

  "federation": "referrals",

  "pageSize": 5

}

In addition to the `query` object (§7.1), Search accepts:

| Field | Type | Description |
| :---- | :---- | :---- |
| federation | String | Optional. auto (default), referrals, or none. |
| pageSize | Integer | Optional. Maximum number of results. |

Response Schema:

The response returns standard catalog entries with additional relevance scores, plus optional referrals. The score parameter denotes semantic relevance ranking (0-100) computed by the search registry, indicating how well the entry satisfies the natural language query criteria. It is strictly an informational relevance metric and MUST NOT be interpreted by orchestrators as a cryptographic trust, compliance, or safety rating. Trust evaluation is fully decoupled and handled independently via the verification procedures in the trustManifest layer.

{

  "results": \[

    {

      "identifier": "urn:ai:acme.com:agent:assistant",

      "displayName": "Corporate Assistant (A2A)",

      "type": "application/a2a-agent-card+json",

      "url": "https://api.acme.com/agents/assistant.json",

      "score": 95,

      "source": "https://registry.acme.com/api/v1/"

    },

    {

      "identifier": "urn:ai:example.com:weather-server",

      "displayName": "Global Weather Service",

      "type": "application/mcp-server+json",

      "url": "https://weather.example.com/mcp",

      "capabilities": \["WeatherTool"\],

      "score": 88,

      "source": "https://finder.external.org/api/"

    }

  \],

  "referrals": \[

    {

      "identifier": "urn:ai:nlweb.ai:registry:public",

      "displayName": "Public Agent Finder",

      "type": "application/ai-registry",

      "url": "https://finder.nlweb.ai/search"

    }

  \],

  "pageToken": "eyJwYWdlIjogMn0="

}

#### 7.2.1 Query Processing and Resolution (Informative)

While this specification mandates the REST interface for interoperability, implementations may employ advanced techniques to resolve natural language queries to specific agent endpoints. An example flow, drawing from research on Agent Naming Services (ANS) and Federated Registries, involves the following steps:

Semantic Translation & Embedding:

- LLM Query Interpretation: The Registry uses an LLM to extract specific multi-dimensional requirements from the natural language text field, translating it into structured capability attributes (e.g., domain: travel, skill: flight\_booking, constraints: meal\_preference).  
- Vector Embeddings: The Registry may also convert the query description into a dense vector embedding to understand semantic meaning (e.g., matching "foreign exchange" to "forex" or "international money transfer").

Global Discovery via Federated Routing:

- Advanced implementations may execute this query against a federated network. For example, using semantic attributes or embedding vectors to perform a search across a Distributed Hash Table (DHT) (e.g., an extended IPFS Kademlia DHT) or by leveraging DNS-AID to discover authoritative registries for specific domains.  
- This maps the semantic capabilities to cryptographic digests or endpoints of agents that possess those skills across the federated network.

### 7.3 Explore (POST /explore) — Optional

Accepts a `query` (§7.1) and returns an aggregation over the matched set rather than ranked entries. Explore lets clients introspect a registry — for example, "which media types are available?" — and obtain facet breakdowns narrowed by the same `text` and `filter` as Search. For Explore, `text` and `filter` are both optional; when both are absent, the aggregation covers the entire registry.

Request Schema:

{

  "query": {

    "text": "currency conversion",

    "filter": {

      "trustManifest.attestations.type": \["SOC2-Type2"\]

    }

  },

  "resultType": {

    "facets": \[

      { "field": "type" },

      { "field": "publisher", "limit": 50 }

    \]

  }

}

In addition to the `query` object (§7.1), Explore accepts:

| Field | Type | Description |
| :---- | :---- | :---- |
| resultType | Object | Required. The shape of result to compute. The only defined shape is facets (below); future shapes such as counts or sample extend this field without protocol changes. |

Each element of resultType.facets:

| Field | Type | Description |
| :---- | :---- | :---- |
| field | String | Required. Field path to aggregate (same syntax as filter keys, §7.1). |
| limit | Integer | Optional. Maximum number of buckets returned. Default: 20\. |
| minCount | Integer | Optional. Suppress buckets with counts below this threshold. |

Response Schema:

{

  "resultType": "facets",

  "facets": {

    "type": {

      "buckets": \[

        { "value": "application/mcp-server+json", "count": 1247 },

        { "value": "application/a2a-agent-card+json", "count": 389 }

      \],

      "otherCount": 23

    },

    "publisher": {

      "buckets": \[

        { "value": "acme.com", "count": 412 }

      \]

    }

  }

}

Each bucket carries value and SHOULD carry count (the number of matching entries; a registry MAY omit it where counts cannot be computed efficiently). otherCount reports the number of matching entries in buckets beyond limit.

Facets are computed over the full matched set, not a single page. For semantic text queries, the registry applies a relevance cutoff: entries whose relevance falls below the cutoff are excluded from the matched set. The cutoff is registry-defined, but within a single registry the same cutoff governs both Search results and Explore facets. The cutoff and the relevance score (§7.2) reflect relevance only and MUST NOT be interpreted as a trust, compliance, or safety judgment.

Explore does not federate; it is scoped to the registry queried. Federated discovery is the role of Search (§8). A registry that does not implement Explore returns 501 Not Implemented.

### 7.4 List (GET /agents) — Optional

Deterministic browsing, designed for developer portals. Highly cacheable, relies on strict database filtering, and does not support relevance-based sorting.

Parameters:

| Parameter | Type | Description |
| :---- | :---- | :---- |
| filter | String | EBNF filter expression. |
| orderBy | String | Sorting fields (e.g., name, created\_at DESC). |
| pageSize | Integer | Max results (default: 20, max: 100). |
| pageToken | String | Pagination token. |

### 7.5 Protocol Wrappers (Optional)

While the REST API is mandated as the floor for interoperability, a Registry MAY additionally expose its search capability natively via an MCP Tool or an A2A Skill to preserve native orchestrator flows.

The return response from these protocol-specific wrappers MUST follow the same catalog entry format as defined in this specification. However, the request format for these wrappers may differ slightly to accommodate protocol-specific conventions and is pending further definition.

## 8\. Federation

Because the REST API is mandated, Registry-to-Registry routing (federation) becomes a simple HTTP operation. The client controls federation through the federation parameter:

- auto: The Registry queries upstream registries automatically, merges their results with its own, and returns a unified response. The client gets a single merged result set.  
- referrals: The Registry returns its results plus catalog entries for other Registries the client may query. The client decides which to follow.  
- none: The Registry searches only its own index.

This gives the client full control over the federation topology without requiring complex protocol translation layers.

Example: Referrals Mode

Request:

{

  "query": {

    "text": "find me a flight booking agent"

  },

  "federation": "referrals"

}

Response:

{

  "results": \[

    {

      "identifier": "urn:ai:acme.com:agent:expense",

      "displayName": "Corporate Expenses",

      "type": "application/a2a-agent-card+json",

      "url": "https://internal.corp/agents/expense.json",

      "score": 97,

      "source": "https://finder.internal.corp"

    }

  \],

  "referrals": \[

    {

      "identifier": "urn:ai:nlweb.ai:registry:public",

      "displayName": "Public Agent Finder",

      "type": "application/ai-registry",

      "url": "https://finder.nlweb.ai/search"

    },

    {

      "identifier": "urn:ai:example.com:registry:travel",

      "displayName": "Travel Agent Finder",

      "type": "application/ai-registry",

      "url": "https://travel.finder.example/search"

    }

  \]

}

## 9\. Integration Example

A user asks an orchestrator: "Book me a flight to Tokyo and file the travel expense report."

- The orchestrator queries the enterprise Agent Registry with federation: "referrals".  
- The Registry returns an internal expense agent, plus referrals to other Registries.  
- The orchestrator follows a referral to a public Agent Registry and queries it for flight booking agents.  
- The orchestrator now has both capabilities and can proceed to invoke them using their respective protocols (e.g., A2A for booking, MCP for expense filing).

## Appendix A: Filter Expression Syntax

The `filter` parameter of the GET /agents endpoint (§7.4) uses a simple EBNF-like format for structured constraints, encoded as a query-parameter string. The POST /search and POST /explore endpoints use the structured query model of §7.1 instead; this EBNF form exists because the GET query-parameter transport cannot carry a JSON body. Both express attribute constraints over the same underlying index.

| Filter Field | Type | Description |
| :---- | :---- | :---- |
| displayName | String | Case-insensitive name filter. |
| type | String | Comma-separated media types (OR logic). |
| publisherId | String | Comma-separated publisher IDs (OR logic). |
| createdAfter | String | ISO 8601 timestamp. |
| updatedAfter | String | ISO 8601 timestamp. |

Logical AND is used across different parameters; OR is used within a single parameter with multiple values (comma-separated).

## Appendix B: Standard Error Codes

| HTTP Code | Error Code | Description |
| :---- | :---- | :---- |
| 400 | INVALID\_ARGUMENT | Malformed query or invalid filter syntax. |
| 401 | UNAUTHENTICATED | Invalid or missing credentials. |
| 404 | NOT\_FOUND | Non-existent agent or registry. |
| 429 | RATE\_LIMIT\_EXCEEDED | Too many requests. |
| 500 | INTERNAL\_ERROR | Internal server failure. |
| 501 | NOT\_IMPLEMENTED | Endpoint not implemented by this registry (e.g., the optional /explore endpoint). |

## Appendix C: Agent Naming URN format

Restricting the discovery identifier to this specific URN format, rather than allowing arbitrary URIs (such as https://... or spiffe://...), provides fundamental architectural benefits for federated agent discovery:

- Nomenclature Stability (Immutable Noun vs. Mutable Location): Arbitrary URIs, particularly HTTP URLs, conflate the logical identity of a capability with its physical network location. If an enterprise migrates workloads across cloud providers, restructures its API gateway, or alters its deployment clusters, an HTTP URL breaks. The urn:ai: identifier acts as an abstract, permanent contract (the "noun"). Physical distribution and transport bindings are decoupled into the url or data fields, allowing underlying infrastructure to evolve without breaking client discovery, indexing, or orchestration code.  
- Strict Separation of Concerns: Federated search registries require a clean, stable primary key to index capabilities efficiently across global networks. Conversely, zero-trust execution runtimes require dynamic, verifiable cryptographic tokens (SPIFFE IDs, DIDs, X.509 certificates) to authenticate workloads. Forcing a single URI to serve both roles creates an architectural bottleneck. The urn:ai: format cleanly decouples the searchable discovery handle from the security principal, allowing the discovery index and the security mesh to operate independently.  
- Decentralized Trust and Authority Binding: In a globally federated open discovery network, search registries must prevent malicious actors from claiming namespaces they do not own (e.g., an untrusted publisher claiming urn:ai:google.com:tax-agent). Mandating that \<publisher\> be a valid FQDN establishes an immediate, verifiable authority anchor. Registries and orchestrators programmatically extract the domain from the URN (google.com) and cross-reference it with the cryptographic claim in trustManifest.identity. If the workload cannot produce a valid cryptographic attestation (e.g., mTLS certificate or SPIFFE SVID) issued by google.com, the capability is rejected. This ensures decentralized, zero-trust verification without requiring a centralized naming committee.  
- Search and Discovery Ergonomics (The @ Resolution Pattern): Users and LLMs require intuitive, semantic handles for capabilities (e.g., Assistant@Acme). The structured hierarchy of urn:ai:\<publisher\>:\<namespace\>:\<agent-name\> allows search engines and federated registries to parse components deterministically. Registries can easily match natural language queries to the publisher domain (Acme) and the terminal short name (Assistant), enabling high-performance semantic filtering, aggregation, and conflict resolution (e.g., displaying Assistant with a verified Acme shield).  
- Cross-Network Uniqueness and Federation Scalability: Domain-anchored URNs guarantee global uniqueness across disparate federated registries without requiring centralized registration databases. Because domain names are already globally unique via the DNS root, anchoring the URN to a domain eliminates collision risks when merging catalogs from multiple upstream registries in auto or referrals federation modes.
