# ⚠️ DEPRECATED

**This directory is deprecated as of 2026-02-05.**

## Migration

This codebase has been consolidated into `unified-agent/`. All new development should happen there.

### What moved where:

| Old Location | New Location |
|--------------|--------------|
| `agent/src/ai_agent/tools/` | `unified-agent/src/unified_agent/tools/` |
| `agent/src/ai_agent/` | `unified-agent/src/unified_agent/core/` |
| `agent/Dockerfile` | `unified-agent/Dockerfile` |

### Key changes in unified-agent:

1. **Multi-model support**: LiteLLM-based (Claude, Gemini, OpenAI)
2. **Config-driven agents**: Define agents via JSON config
3. **Sandbox isolation**: gVisor-based Kubernetes sandboxes
4. **Skills system**: Progressive disclosure of domain knowledge

### Migration steps:

1. Update imports from `ai_agent` to `unified_agent`
2. Update Dockerfile references to `unified-agent/Dockerfile`
3. Update Kubernetes manifests to use new image

## Timeline

- **Now**: Use `unified-agent/` for all new development
- **TBD**: This directory will be removed after validation

## Questions?

See `unified-agent/README.md` for documentation.
