# ⚠️ DEPRECATED

**This directory is deprecated as of 2026-02-05.**

## Migration

This codebase has been consolidated into `unified-agent/`. All new development should happen there.

### What moved where:

| Old Location | New Location |
|--------------|--------------|
| `sre-agent/providers/` | `unified-agent/src/unified_agent/providers/` |
| `sre-agent/sandbox_server.py` | `unified-agent/src/unified_agent/sandbox/server.py` |
| `sre-agent/sandbox_manager.py` | `unified-agent/src/unified_agent/sandbox/manager.py` |
| `sre-agent/auth.py` | `unified-agent/src/unified_agent/sandbox/auth.py` |
| `sre-agent/events.py` | `unified-agent/src/unified_agent/core/events.py` |
| `sre-agent/.claude/skills/` | `unified-agent/src/unified_agent/skills/bundled/` |
| `sre-agent/Dockerfile` | `unified-agent/Dockerfile` |

### Key changes in unified-agent:

1. **Unified architecture**: Combines agent/ tools with sre-agent sandbox
2. **Multi-model support**: LiteLLM-based (Claude, Gemini, OpenAI)
3. **Config-driven agents**: Define agents via JSON config
4. **Tool registry**: 80+ tools with lazy loading

### Migration steps:

1. Update Dockerfile references to `unified-agent/Dockerfile`
2. Update Kubernetes sandbox CRD to use new image
3. Update ConfigMaps for agent configuration

## Timeline

- **Now**: Use `unified-agent/` for all new development
- **TBD**: This directory will be removed after validation

## Questions?

See `unified-agent/README.md` for documentation.
