# Minimal transport and observation surface

Do not begin with a custom API or MCP server when a simpler observable surface already exposes the needed information.

For read-only retrieval, prefer the least expensive interface that preserves the information and failure state you need.

## Escalation ladder

1. **Python value / local file / static artifact**
   - Read it directly with `pathlib`, `json`, `csv`, `zipfile`, etc.
2. **Raw document over HTTP**
   - Use `urllib.request` from the standard library or an existing `curl`.
   - If the whole HTML/text document is the useful payload, keep it whole.
3. **Generic local parsing**
   - Use `html.parser`, `json`, `csv`, `xml.etree.ElementTree`, regular expressions only where appropriate, or an existing repository parser.
   - Extract only when a consumer actually benefits from structure.
4. **Official HTTP API**
   - Escalate when authentication, stable field schemas, pagination, rate-limit semantics, server-side filtering/search, mutation, or expensive server-side computation are real requirements.
5. **MCP / richer tool protocol**
   - Escalate when tool discovery, typed tool invocation, sessions/resources/prompts, capability negotiation, or agent integration is itself part of the contract.

An API or MCP endpoint is valuable when it adds a contract. It is unnecessary overhead when it merely re-publishes the same complete document without adding auth, mutation, filtering, stability, or computation.

## Full documents are legitimate machine interfaces

A static HTML page is already structured data.

For a small/read-only site, this can be enough:

```python
from urllib.request import urlopen

with urlopen(url, timeout=10) as response:
    html = response.read().decode("utf-8")
```

A human can read it. An AI can read it. A parser can inspect it later if needed.

Do not create a JSON API solely because JSON feels more machine-oriented if the existing HTML already contains all required information and its layout is sufficiently stable for the use case.

## Parse only as far as needed

If a consumer only needs headings, a tiny `html.parser.HTMLParser` subclass can extract headings without introducing a web framework, browser, DOM package, or server API.

If the repository already has a canonical parser—such as the shared markdown/HTML helpers—reuse it instead of duplicating parsing logic.

The escalation is therefore:

`raw bytes/text -> generic parser -> domain parser -> API/MCP only when the contract requires it`.

## Failure is also information

“No result” and “request failed” should remain observable states.

Examples:

- HTTP 404: resource does not exist at that path.
- HTTP 401/403: authentication/authorization is required or denied.
- HTTP 429: rate policy is active.
- HTTP 5xx: upstream/server failure.
- curl non-zero: transport/tool-level failure.
- subprocess launch failure: local executable/environment problem.

Do not turn every failure into an empty successful payload.

For a read-only probe, returning/recording the original status may be more useful than inventing a retrying abstraction.

## Logging before shell echo conventions

Do not build shell-specific timestamp/level prefixes when Python is already the orchestration layer.

Use `logging`:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("probe")
logger.info("fetch_complete")
```

This gives timestamp, level, logger identity and message without a chain of `date`, `echo`, environment variables and exit-code relays.

For machine evidence, prefer JSON/JSONL/JUnit or another already-defined structured record rather than parsing human log text.

## Cost model

Each extra interface has two costs:

- **producer cost**: implementation, schema/versioning, auth, hosting, logs, compatibility, tests;
- **consumer cost**: client code, protocol knowledge, auth/session setup, retries, parsing and failure handling.

Choose API/MCP when those costs buy an actual contract.

For a public static technical report, documentation site, fixture, or small index, direct document retrieval may be the more maintainable interface.

## Boundaries

This is not an argument against APIs or MCP.

Use an API when:
- callers need stable structured fields independent of presentation;
- only a subset of a large dataset should cross the network;
- server-side search/filtering/aggregation materially reduces work;
- authentication/authorization or mutation is required;
- rate limits, cursors, transactions, or consistency semantics matter.

Use MCP when:
- the agent-facing tool protocol itself is valuable;
- multiple typed operations need discovery and consistent invocation;
- resources/prompts/tool schemas or session state are part of the product contract.

Otherwise, do not manufacture protocol layers before the simpler surface fails a real requirement.

## Evidence in PR #1

`tests/test_observation_surface.py` verifies with only the standard library:

- a static HTML document can be fetched in full over real localhost HTTP;
- the same document can be minimally inspected with `html.parser`;
- a missing path remains a real HTTP 404 rather than an empty success;
- stdlib logging emits level/logger/message metadata without shell echo plumbing.

These tests demonstrate the decision boundary; `cli_args.py` itself gains no HTTP or HTML-specific API.
