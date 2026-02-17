---
name: kafka-streaming
description: Kafka topic and consumer group management. Use when investigating Kafka topics, consumer lag, broker health, or consumer group status.
allowed-tools: Bash(python *)
---

# Kafka Streaming

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `KAFKA_SASL_PASSWORD` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `KAFKA_BOOTSTRAP_SERVERS` - Kafka broker addresses
- `KAFKA_SECURITY_PROTOCOL` - Security protocol (PLAINTEXT, SSL, SASL_SSL, SASL_PLAINTEXT)

---

## MANDATORY: Broker-First Investigation

**Start with broker info, then check topics and consumer groups.**

```
BROKER INFO → LIST TOPICS → DESCRIBE TOPIC → CHECK CONSUMER LAG
```

## Available Scripts

All scripts are in `.claude/skills/streaming-kafka/scripts/`

### get_broker_info.py - ALWAYS START HERE
```bash
python .claude/skills/streaming-kafka/scripts/get_broker_info.py
```

### list_topics.py - List Topics
```bash
python .claude/skills/streaming-kafka/scripts/list_topics.py [--include-internal]
```

### describe_topic.py - Topic Details with Offsets
```bash
python .claude/skills/streaming-kafka/scripts/describe_topic.py --topic TOPIC_NAME
```

### list_consumer_groups.py - List Consumer Groups
```bash
python .claude/skills/streaming-kafka/scripts/list_consumer_groups.py
```

### describe_consumer_group.py - Consumer Group Details
```bash
python .claude/skills/streaming-kafka/scripts/describe_consumer_group.py --group GROUP_ID
```

### get_consumer_lag.py - Consumer Lag with Health Assessment
```bash
python .claude/skills/streaming-kafka/scripts/get_consumer_lag.py --group GROUP_ID [--topic TOPIC]
```

---

## Consumer Lag Health Levels
| Total Lag | Health |
|-----------|--------|
| 0 | healthy |
| < 1,000 | minor_lag |
| < 100,000 | lagging |
| >= 100,000 | severely_lagging |

---

## Investigation Workflow

### Consumer Lag Investigation
```
1. get_broker_info.py (verify cluster health)
2. list_consumer_groups.py (find the group)
3. get_consumer_lag.py --group <group-id> (check lag)
4. describe_topic.py --topic <topic> (check partition details)
```

### Topic Issue Investigation
```
1. list_topics.py
2. describe_topic.py --topic <topic> (partitions, configs, offsets)
3. Check under-replicated partitions in output
```
