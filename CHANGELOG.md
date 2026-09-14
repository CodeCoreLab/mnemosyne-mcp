# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- First public release
- 17 MCP tools for memory management
- Pure Python client (no MCP required)
- Knowledge graph with temporal triples
- Memory hygiene audit + consolidation
- 20 passing tests
- GitHub Actions CI (Python 3.10-3.12)

## [0.1.0] - 2026-09-15

### Added
- Initial release of `mnemosyne-mcp`
- `MnemosyneClient`: pure Python SQLite client
- MCP server: stdio + SSE transport
- Memory CRUD: remember / recall / get / update / forget / invalidate
- Knowledge graph: triple_add / triple_query / triple_end / graph_link / graph_query
- Memory management: sleep / scratchpad / hygiene_audit / stats
- Shared surface: shared_remember / shared_recall
- CLI: `mnemosyne-mcp serve` / `mnemosyne-mcp init`
