---
name: docker-debugging
description: Docker container debugging and management. Use when investigating container issues, checking logs, resource usage, or Docker Compose services.
allowed-tools: Bash(python *)
---

# Docker Debugging

## Authentication

Docker commands run directly via the Docker CLI. No API keys are needed - the Docker socket must be accessible in the sandbox environment.

---

## Available Scripts

All scripts are in `.claude/skills/infrastructure-docker/scripts/`

### container_ps.py - List Containers
```bash
python .claude/skills/infrastructure-docker/scripts/container_ps.py [--all]
```

### container_logs.py - Get Container Logs
```bash
python .claude/skills/infrastructure-docker/scripts/container_logs.py --container NAME_OR_ID [--tail 100]
```

### container_inspect.py - Inspect Container
```bash
python .claude/skills/infrastructure-docker/scripts/container_inspect.py --container NAME_OR_ID
```

### container_exec.py - Execute Command in Container
```bash
python .claude/skills/infrastructure-docker/scripts/container_exec.py --container NAME_OR_ID --command "ls -la /app"
```

### container_stats.py - Resource Usage Statistics
```bash
python .claude/skills/infrastructure-docker/scripts/container_stats.py [--container NAME_OR_ID]
```

### image_list.py - List Docker Images
```bash
python .claude/skills/infrastructure-docker/scripts/image_list.py [--filter "reference=myapp*"]
```

### compose_ps.py - List Compose Services
```bash
python .claude/skills/infrastructure-docker/scripts/compose_ps.py [--file docker-compose.yml] [--cwd /path]
```

### compose_logs.py - Get Compose Service Logs
```bash
python .claude/skills/infrastructure-docker/scripts/compose_logs.py [--services "api,db"] [--tail 100]
```

---

## Investigation Workflow

### Container Debugging
```
1. List containers: container_ps.py --all
2. Check logs: container_logs.py --container <name> --tail 200
3. Check resources: container_stats.py --container <name>
4. Inspect config: container_inspect.py --container <name>
5. Run diagnostics: container_exec.py --container <name> --command "curl -s localhost:8080/health"
```

### Docker Compose Debugging
```
1. Check services: compose_ps.py
2. Check logs: compose_logs.py --services "api,worker" --tail 100
```

---

## Anti-Patterns to Avoid

1. **Never run destructive commands** without explicit user approval (docker rm, docker rmi, docker system prune)
2. **Always use --tail** for logs to avoid overwhelming output
3. **Check container status first** before trying to exec into it
