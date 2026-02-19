# Contributing to IncidentFox

Thank you for your interest in contributing to IncidentFox! We're building an AI-powered SRE that helps teams investigate incidents and automate infrastructure operations.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Pull Request Process](#pull-request-process)
- [Style Guidelines](#style-guidelines)
- [Community](#community)

## Code of Conduct

By participating in this project, you agree to maintain a respectful, inclusive, and collaborative environment. We're here to build great software together.

## Licensing

IncidentFox uses a dual-license model. Before contributing, please understand:

- **Contributions to core components** (those under Apache 2.0) are licensed
  under the Apache License 2.0.
- **Contributions to enterprise components** (those under BSL 1.1) are licensed
  under the Business Source License 1.1.

See [LICENSING.md](LICENSING.md) for the full directory-to-license mapping.

By submitting a pull request, you agree that your contributions will be licensed
under the same license as the files you are modifying. If your PR spans both
Apache 2.0 and BSL 1.1 components, the respective license applies to each file.

## How Can I Contribute?

### Reporting Bugs

Found a bug? Help us fix it:

1. **Check existing issues** to avoid duplicates
2. **Use the bug report template** when creating a new issue
3. **Include details**: steps to reproduce, expected vs actual behavior, logs, environment info
4. **Add labels** if you can (bug, high-priority, etc.)

### Suggesting Features

Have an idea? We'd love to hear it:

1. **Check existing feature requests** in [Discussions](https://github.com/incidentfox/incidentfox/discussions)
2. **Open a discussion** in the Ideas category before creating an issue
3. **Explain the use case** and why it matters for incident response
4. **Consider the scope** — does this fit IncidentFox's mission?

### Contributing Code

Look for issues labeled:
- `good first issue` — beginner-friendly tasks
- `help wanted` — we'd love community contributions here
- `documentation` — help improve our docs

## Getting Started

### Prerequisites

- **Python 3.11+** with `uv` (recommended) or `pip`
- **Docker & Docker Compose** for local development
- **Node.js 18+** for the web frontend
- **PostgreSQL 16+** (or use Docker)

### Local Setup

1. **Clone the repository**

```bash
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox
```

2. **Install dependencies**

```bash
# Backend (Python)
uv pip install -e ".[dev]"

# Frontend (Node.js)
cd frontend && npm install
```

3. **Set up environment**

```bash
cp .env.example .env
# Edit .env with your API keys (see README for details)
```

4. **Start services**

```bash
docker-compose up -d postgres redis
python -m incidentfox.orchestrator &
python -m incidentfox.agent &
cd frontend && npm run dev
```

5. **Run tests**

```bash
pytest                          # Backend tests
cd frontend && npm test        # Frontend tests
```

See [DEVELOPMENT_KNOWLEDGE.md](DEVELOPMENT_KNOWLEDGE.md) for detailed architecture and development guide.

## Development Workflow

### Branching Strategy

- `main` — stable, production-ready code
- `develop` — integration branch for features
- `feature/your-feature` — your feature branch
- `fix/your-fix` — bug fix branch

### Making Changes

1. **Create a branch**

```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes**
   - Write clean, readable code
   - Add tests for new functionality
   - Update documentation as needed

3. **Test locally**

```bash
pytest                                    # Run all tests
pytest tests/test_your_feature.py        # Run specific tests
black . && ruff check .                  # Format and lint
```

4. **Commit with clear messages**

```bash
git commit -m "feat: add alert correlation for Datadog"
```

Use [conventional commits](https://www.conventionalcommits.org/):
- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation changes
- `refactor:` — code refactoring
- `test:` — adding/updating tests
- `chore:` — maintenance tasks

## Pull Request Process

### Before Submitting

- [ ] Tests pass locally (`pytest`)
- [ ] Code is formatted (`black .` and `ruff check .`)
- [ ] Documentation is updated
- [ ] Commit messages follow conventional commits
- [ ] Branch is up to date with `main`

### Submitting Your PR

1. **Push your branch**

```bash
git push origin feature/your-feature-name
```

2. **Create a Pull Request**
   - Use a clear, descriptive title
   - Fill out the PR template completely
   - Link related issues (`Closes #123`)
   - Add screenshots/videos for UI changes

3. **Respond to feedback**
   - Address review comments promptly
   - Push changes to the same branch
   - Re-request review when ready

### Review Process

- PRs require **at least one approval** from a maintainer
- CI checks must pass (tests, linting, type checking)
- For large changes, expect multiple review rounds
- We aim to review PRs within 2-3 business days

## Style Guidelines

### Python

- **Formatting**: Use `black` (line length 100)
- **Linting**: Use `ruff` with project config
- **Type hints**: Required for public APIs
- **Docstrings**: Use Google style for functions/classes

```python
def correlate_alerts(alerts: list[Alert], threshold: float = 0.8) -> list[AlertGroup]:
    """Correlate alerts using temporal and semantic similarity.

    Args:
        alerts: List of alerts to correlate
        threshold: Similarity threshold (0.0 to 1.0)

    Returns:
        List of correlated alert groups
    """
    pass
```

### TypeScript/React

- **Formatting**: Use Prettier
- **Linting**: Use ESLint with project config
- **Components**: Functional components with TypeScript
- **State**: Use React hooks, avoid class components

### Git Commit Messages

- Start with a conventional commit type
- Keep first line under 72 characters
- Use present tense ("add feature" not "added feature")
- Reference issues/PRs in body

```
feat: add Prometheus alert correlation

- Implement temporal correlation algorithm
- Add semantic similarity using embeddings
- Include tests for edge cases

Closes #123
```

## Community

### Get Help

- **GitHub Discussions** — ask questions, share ideas
- **Slack** — join our community at [incidentfox.slack.com](https://join.slack.com/t/incidentfox/shared_invite/zt-3ojlxvs46-xuEJEplqBHPlymxtzQi8KQ)
- **Issues** — report bugs or request features

### Stay Updated

- Watch this repo for updates
- Follow [@incidentfox](https://twitter.com/incidentfox) on Twitter
- Read our [blog](https://incidentfox.ai/blog) for deep dives

### Recognition

Contributors are recognized in:
- [CONTRIBUTORS.md](CONTRIBUTORS.md) — all contributors listed
- GitHub contributor graph
- Release notes for significant contributions

## Questions?

If you're unsure about anything:
1. Check [DEVELOPMENT_KNOWLEDGE.md](DEVELOPMENT_KNOWLEDGE.md) for technical details
2. Ask in [GitHub Discussions](https://github.com/incidentfox/incidentfox/discussions)
3. Reach out to maintainers in Slack

**Thank you for making IncidentFox better!** 🦊
