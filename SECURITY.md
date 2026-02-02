# Security Policy

## Supported Versions

We release security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| Latest release | :white_check_mark: |
| Older releases | :x: |

We strongly recommend running the latest version of IncidentFox.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via one of these methods:

### 1. GitHub Security Advisories (Preferred)

Report security vulnerabilities privately through GitHub:

1. Go to the [Security tab](https://github.com/incidentfox/incidentfox/security)
2. Click "Report a vulnerability"
3. Fill out the advisory form with details

### 2. Email

Send details to **security@incidentfox.ai** with:

- Type of vulnerability (RCE, injection, XSS, etc.)
- Affected component(s)
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### What to Expect

- **Acknowledgment**: Within 24 hours
- **Initial assessment**: Within 3 business days
- **Regular updates**: At least every 7 days until resolved
- **Disclosure timeline**: Coordinated disclosure after patch is available

We follow responsible disclosure practices and will credit reporters (unless you prefer to remain anonymous).

## Scope

### In Scope

Security issues in:

- **IncidentFox core** (agent, orchestrator, config-service)
- **Web console** (authentication, authorization, XSS, CSRF)
- **API endpoints** (injection, authentication bypass)
- **Slack bot** (command injection, unauthorized access)
- **Integrations** (credential leakage, SSRF)
- **Deployment configs** (Kubernetes, Docker)
- **Dependencies** (critical CVEs in direct dependencies)

### Out of Scope

- Social engineering attacks
- Physical attacks
- Attacks requiring MITM on local network
- DoS/DDoS attacks
- Issues in third-party services (Slack, AWS, etc.)
- Issues only exploitable with admin access
- Theoretical vulnerabilities without proof of concept
- Brute force attacks without additional vulnerability

## Security Best Practices

When deploying IncidentFox:

### Secrets Management

- **Never commit secrets** to version control
- Use **secrets proxy** in production (see [deployment guide](docs/DEPLOYMENT.md))
- Rotate credentials regularly
- Use separate credentials for dev/staging/prod

### Network Security

- Deploy behind a firewall
- Use TLS for all external communications
- Restrict API access to authorized networks
- Enable audit logging

### Authentication & Authorization

- Enable SSO/OIDC for production deployments
- Use role-based access control (RBAC)
- Review team permissions regularly
- Enable approval workflows for critical changes

### Agent Sandboxing

- Use **Claude Sandbox** in production (isolated Kubernetes namespaces)
- Limit agent permissions to minimum required
- Monitor agent actions via audit logs
- Review tool usage patterns

### Updates & Monitoring

- Subscribe to security announcements (watch this repo)
- Update IncidentFox regularly
- Monitor dependency vulnerabilities (Dependabot enabled)
- Review audit logs for suspicious activity

## Known Security Considerations

### Agent Tool Execution

IncidentFox agents execute commands against your infrastructure (kubectl, AWS CLI, etc.). This is by design for incident response.

**Mitigations:**
- Tools run in isolated sandboxes
- Secrets never touch the agent (injected by proxy)
- Approval workflows for critical operations
- Full audit trail of all actions

### LLM Prompt Injection

Like all LLM-powered tools, IncidentFox may be susceptible to prompt injection attacks.

**Mitigations:**
- Input validation and sanitization
- Separate system and user contexts
- Tool-specific safety checks
- Human approval for destructive operations

### Data Privacy

Agents may access sensitive data (logs, metrics, code).

**Mitigations:**
- On-premise deployment option (full data control)
- Configurable data retention policies
- Audit logs for data access
- RBAC for sensitive integrations

## Security Features

IncidentFox includes security features for production:

- **SOC 2 compliant** infrastructure (managed deployments)
- **End-to-end encryption** for data in transit
- **Secrets proxy** (credentials never touch agents)
- **Audit logging** (all actions tracked)
- **RBAC** (role-based access control)
- **SSO/OIDC** support
- **Approval workflows** for critical changes
- **Isolated sandboxes** (Kubernetes namespaces per agent)

See [Enterprise Ready](README.md#enterprise-ready) for details.

## Vulnerability Disclosure Policy

When we receive a security report:

1. **Confirmation**: We confirm the vulnerability
2. **Patch development**: We develop and test a fix
3. **Coordinated disclosure**: We coordinate with the reporter on disclosure timeline
4. **Release**: We release a patch and security advisory
5. **Public disclosure**: We publicly disclose the issue (typically 90 days after patch)

We credit security researchers in:
- Security advisories
- Release notes
- Public acknowledgments (if desired)

## Security Hall of Fame

We recognize security researchers who help keep IncidentFox secure:

<!-- This section will be updated as we receive security reports -->

*No security issues reported yet. Be the first!*

## Contact

- **Security issues**: security@incidentfox.ai
- **General questions**: founders@incidentfox.ai
- **Community**: [Slack](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ) | [Discussions](https://github.com/incidentfox/incidentfox/discussions)

## Learn More

- [Deployment Guide](docs/DEPLOYMENT.md) — production deployment best practices
- [Architecture](docs/ARCHITECTURE.md) — system design and security architecture
- [Enterprise Ready](README.md#enterprise-ready) — advanced security features
