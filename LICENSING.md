# IncidentFox Licensing

IncidentFox uses a dual-license model.

## Summary

| Component | License | SPDX |
|-----------|---------|------|
| Core platform | [Apache License 2.0](LICENSE) | Apache-2.0 |
| Security layer | [Business Source License 1.1](LICENSE-ENTERPRISE) | BUSL-1.1 |

The security layer automatically converts to Apache 2.0 on the Change Date
(February 18, 2030) or 4 years after each version's first release, whichever
comes first.

## What is Apache 2.0 (Core)?

The core platform is fully open source. You can use, modify, and deploy it
freely, including in production, without any commercial license. This includes
everything in the repository except the security layer listed below.

## What is BSL 1.1 (Security Layer)?

The production security layer is source-available under the Business Source
License 1.1. You can read, modify, and use it for development, testing,
evaluation, and non-commercial purposes. Production use requires a commercial
license from IncidentFox, Inc.

These components provide sandbox isolation and zero-knowledge credential
injection for production deployments:

| Path | Description |
|------|-------------|
| `sre-agent/sandbox_manager.py` | gVisor K8s sandbox pod management |
| `sre-agent/sandbox_server.py` | Sandbox-internal FastAPI server |
| `sre-agent/credential-proxy/` | Zero-knowledge secret injection (Envoy + resolver) |
| `sre-agent/sandbox-router/` | Sandbox request routing |
| `sre-agent/Dockerfile` | Production hardened container image |

BSL-licensed files have a license header and/or a directory-level `LICENSE` file.

## How to determine the license for a file

1. Check if the file has a license header — that takes precedence.
2. Check if the file's directory contains a `LICENSE` file — that applies.
3. Otherwise, the root `LICENSE` (Apache 2.0) applies.

## Commercial Licensing

For production use of enterprise features, contact: licensing@incidentfox.ai

## Contributing

Contributions to Apache 2.0 components are under Apache 2.0.
Contributions to BSL 1.1 components are under BSL 1.1.
See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
