"""
Slack Environment Scanner.

Scans a Slack workspace to discover what tools and integrations
the team uses, by analyzing channel names, message content, and shared URLs.
"""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse


def _log(event: str, **fields) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": "ai-learning-pipeline",
        "module": "scanners.slack",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str))


@dataclass
class Signal:
    """A discovered signal indicating tool/integration usage."""

    signal_type: str  # "tool_mention", "url", "channel_name"
    integration_id: str  # "grafana", "datadog", etc.
    context: str  # surrounding message text (truncated)
    confidence: float  # 0-1
    source: str  # "slack:#channel-name"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectedMessage:
    """A raw Slack message collected for RAG ingestion."""

    channel_name: str
    channel_id: str
    user: str
    text: str
    ts: str
    thread_ts: Optional[str] = None


@dataclass
class ScanResult:
    """Result of scanning a Slack workspace."""

    signals: List[Signal]
    channels_scanned: int
    messages_scanned: int
    scan_duration_ms: float
    collected_messages: List[CollectedMessage] = field(default_factory=list)
    error: Optional[str] = None


# Tool detection patterns: integration_id -> (regex patterns, URL domains)
TOOL_PATTERNS: Dict[str, Dict[str, Any]] = {
    "grafana": {
        "keywords": [r"\bgrafana\b", r"\bdashboard\b.*\bmetric"],
        "domains": ["grafana.com", "grafana.net"],
        "url_paths": ["/grafana/", "/d/"],
    },
    "datadog": {
        "keywords": [r"\bdatadog\b", r"\bdatadoghq\b", r"\bdd[- ]agent\b"],
        "domains": ["datadoghq.com", "datadoghq.eu", "ddog-gov.com"],
        "url_paths": [],
    },
    "pagerduty": {
        "keywords": [
            r"\bpagerduty\b",
            r"\bpd[- ]alert\b",
            r"\bon[- ]?call\b.*schedule",
        ],
        "domains": ["pagerduty.com"],
        "url_paths": [],
    },
    "github": {
        "keywords": [r"github\.com/\S+", r"\bgh\s+pr\b", r"\bpull\s+request\b"],
        "domains": ["github.com"],
        "url_paths": [],
    },
    "confluence": {
        "keywords": [r"\bconfluence\b", r"\bwiki\s+page\b", r"\batlassian\b.*wiki"],
        "domains": ["atlassian.net"],
        "url_paths": ["/wiki/"],
    },
    "sentry": {
        "keywords": [r"\bsentry\b", r"\bsentry\.io\b"],
        "domains": ["sentry.io"],
        "url_paths": [],
    },
    "newrelic": {
        "keywords": [r"\bnew\s*relic\b", r"\bnewrelic\b"],
        "domains": ["newrelic.com"],
        "url_paths": [],
    },
    "elasticsearch": {
        "keywords": [r"\belasticsearch\b", r"\belastic\b.*\blog", r"\bkibana\b"],
        "domains": ["elastic.co", "found.io"],
        "url_paths": ["/kibana/", "/app/discover"],
    },
    "prometheus": {
        "keywords": [r"\bprometheus\b", r"\bpromql\b", r"\balertmanager\b"],
        "domains": [],
        "url_paths": ["/prometheus/", "/alertmanager/"],
    },
    "splunk": {
        "keywords": [r"\bsplunk\b"],
        "domains": ["splunk.com", "splunkcloud.com"],
        "url_paths": [],
    },
    "incident_io": {
        "keywords": [r"\bincident\.io\b"],
        "domains": ["incident.io"],
        "url_paths": [],
    },
    "coralogix": {
        "keywords": [r"\bcoralogix\b"],
        "domains": ["coralogix.com"],
        "url_paths": [],
    },
    "loki": {
        "keywords": [r"\bloki\b.*\blog", r"\blogql\b"],
        "domains": [],
        "url_paths": ["/loki/"],
    },
    "jaeger": {
        "keywords": [r"\bjaeger\b", r"\btracing\b.*\bjaeger"],
        "domains": [],
        "url_paths": ["/jaeger/"],
    },
    "opsgenie": {
        "keywords": [r"\bopsgenie\b"],
        "domains": ["opsgenie.com"],
        "url_paths": [],
    },
}

# Channel name patterns that indicate incident/ops relevance
RELEVANT_CHANNEL_PATTERNS = [
    r"incident",
    r"alert",
    r"ops",
    r"oncall",
    r"on-call",
    r"sre",
    r"monitoring",
    r"outage",
    r"prod",
    r"deploy",
    r"infra",
    r"devops",
    r"platform",
    r"reliability",
]


class SlackEnvironmentScanner:
    """
    Scans a Slack workspace to understand a team's tool ecosystem.

    Strategy:
    1. List all public channels
    2. Identify relevant channels (incident/ops names + most active)
    3. Read recent messages (configurable lookback)
    4. Extract signals via pattern matching and URL classification
    """

    def __init__(
        self,
        bot_token: str,
        lookback_days: int = 30,
        max_channels: int = 20,
        max_messages_per_channel: int = 200,
    ):
        self.bot_token = bot_token
        self.lookback_days = lookback_days
        self.max_channels = max_channels
        self.max_messages_per_channel = max_messages_per_channel

    def scan(self) -> ScanResult:
        """Run the full Slack workspace scan."""
        import time

        start = time.time()
        signals: List[Signal] = []
        collected_messages: List[CollectedMessage] = []
        channels_scanned = 0
        messages_scanned = 0

        try:
            # 1. Discover channels
            all_channels = self._list_channels()
            if not all_channels:
                return ScanResult(
                    signals=[],
                    channels_scanned=0,
                    messages_scanned=0,
                    scan_duration_ms=(time.time() - start) * 1000,
                    error="Could not list channels",
                )

            # 2. Extract signals from channel names
            for ch in all_channels:
                name_signals = self._scan_channel_name(ch)
                signals.extend(name_signals)

            # 3. Select channels to scan messages from
            target_channels = self._select_target_channels(all_channels)
            _log(
                "channels_selected",
                total=len(all_channels),
                selected=len(target_channels),
            )

            # 4. Identify which channels are incident/ops-relevant for RAG
            relevant_names: Set[str] = set()
            for ch in target_channels:
                name = ch.get("name", "").lower()
                if any(re.search(p, name) for p in RELEVANT_CHANNEL_PATTERNS):
                    relevant_names.add(name)

            # 5. Scan messages in selected channels
            oldest = datetime.utcnow() - timedelta(days=self.lookback_days)
            for ch in target_channels:
                ch_name = ch["name"]
                collect_for_rag = ch_name.lower() in relevant_names
                ch_signals, msg_count, ch_collected = self._scan_channel_messages(
                    ch["id"], ch_name, oldest, collect_for_rag=collect_for_rag
                )
                signals.extend(ch_signals)
                collected_messages.extend(ch_collected)
                channels_scanned += 1
                messages_scanned += msg_count

            # 6. Deduplicate and aggregate
            signals = self._deduplicate_signals(signals)

            _log(
                "scan_completed",
                channels_scanned=channels_scanned,
                messages_scanned=messages_scanned,
                signals_found=len(signals),
                messages_collected_for_rag=len(collected_messages),
            )

            return ScanResult(
                signals=signals,
                channels_scanned=channels_scanned,
                messages_scanned=messages_scanned,
                scan_duration_ms=(time.time() - start) * 1000,
                collected_messages=collected_messages,
            )

        except Exception as e:
            _log("scan_failed", error=str(e))
            return ScanResult(
                signals=signals,
                channels_scanned=channels_scanned,
                messages_scanned=messages_scanned,
                scan_duration_ms=(time.time() - start) * 1000,
                collected_messages=collected_messages,
                error=str(e),
            )

    def _api_request(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Make a Slack API request."""
        try:
            url = f"https://slack.com/api/{method}"
            if params:
                url = f"{url}?{urllib.parse.urlencode(params)}"

            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {self.bot_token}")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                if not data.get("ok"):
                    _log("slack_api_error", method=method, error=data.get("error"))
                    return None
                return data
        except Exception as e:
            _log("slack_api_request_failed", method=method, error=str(e))
            return None

    def _list_channels(self) -> List[Dict[str, Any]]:
        """List all public channels in the workspace."""
        channels = []
        cursor = None

        while True:
            params = {"limit": 200, "types": "public_channel"}
            if cursor:
                params["cursor"] = cursor

            result = self._api_request("conversations.list", params)
            if not result:
                break

            channels.extend(result.get("channels", []))

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        _log("channels_listed", count=len(channels))
        return channels

    def _select_target_channels(
        self, channels: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Select channels to scan for messages."""
        relevant = []
        others = []

        for ch in channels:
            name = ch.get("name", "").lower()
            if any(re.search(p, name) for p in RELEVANT_CHANNEL_PATTERNS):
                relevant.append(ch)
            else:
                others.append(ch)

        # Sort non-relevant by member count (most active first)
        others.sort(key=lambda c: c.get("num_members", 0), reverse=True)

        # Take all relevant channels + top general channels up to max
        remaining_slots = max(0, self.max_channels - len(relevant))
        selected = relevant + others[:remaining_slots]

        return selected[: self.max_channels]

    def _scan_channel_name(self, channel: Dict[str, Any]) -> List[Signal]:
        """Extract signals from a channel's name and topic."""
        signals = []
        name = channel.get("name", "").lower()
        topic = (channel.get("topic", {}).get("value", "") or "").lower()
        purpose = (channel.get("purpose", {}).get("value", "") or "").lower()
        text = f"{name} {topic} {purpose}"

        for integration_id, patterns in TOOL_PATTERNS.items():
            for pattern in patterns["keywords"]:
                if re.search(pattern, text, re.IGNORECASE):
                    signals.append(
                        Signal(
                            signal_type="channel_name",
                            integration_id=integration_id,
                            context=f"Channel #{name}: {topic[:100]}",
                            confidence=0.6,
                            source=f"slack:#{name}",
                            metadata={"channel_id": channel["id"]},
                        )
                    )
                    break  # One signal per integration per channel

        return signals

    def _scan_channel_messages(
        self,
        channel_id: str,
        channel_name: str,
        oldest: datetime,
        collect_for_rag: bool = False,
    ) -> tuple[List[Signal], int, List[CollectedMessage]]:
        """Scan messages in a channel for tool signals.

        Args:
            collect_for_rag: If True, also collect raw messages for RAG ingestion
                (only for incident/ops-relevant channels).
        """
        signals: List[Signal] = []
        collected: List[CollectedMessage] = []
        messages_scanned = 0

        result = self._api_request(
            "conversations.history",
            {
                "channel": channel_id,
                "oldest": str(oldest.timestamp()),
                "limit": self.max_messages_per_channel,
            },
        )

        if not result:
            return signals, 0, []

        messages = result.get("messages", [])
        messages_scanned = len(messages)

        for msg in messages:
            text = msg.get("text", "")
            if not text or len(text) < 5:
                continue

            ts = float(msg.get("ts", 0))
            msg_time = datetime.fromtimestamp(ts) if ts else datetime.utcnow()

            # Collect for RAG ingestion (incident/ops channels only)
            if collect_for_rag and len(text) >= 20:
                collected.append(
                    CollectedMessage(
                        channel_name=channel_name,
                        channel_id=channel_id,
                        user=msg.get("user", "unknown"),
                        text=text,
                        ts=msg.get("ts", ""),
                        thread_ts=msg.get("thread_ts"),
                    )
                )

            # Check keyword patterns
            for integration_id, patterns in TOOL_PATTERNS.items():
                for pattern in patterns["keywords"]:
                    if re.search(pattern, text, re.IGNORECASE):
                        signals.append(
                            Signal(
                                signal_type="tool_mention",
                                integration_id=integration_id,
                                context=text[:300],
                                confidence=0.7,
                                source=f"slack:#{channel_name}",
                                timestamp=msg_time,
                                metadata={
                                    "channel_id": channel_id,
                                    "message_ts": msg.get("ts"),
                                },
                            )
                        )
                        break

            # Check URLs in message
            urls = self._extract_urls(text)
            for url in urls:
                matched_integration = self._classify_url(url)
                if matched_integration:
                    signals.append(
                        Signal(
                            signal_type="url",
                            integration_id=matched_integration,
                            context=text[:300],
                            confidence=0.9,
                            source=f"slack:#{channel_name}",
                            timestamp=msg_time,
                            metadata={
                                "channel_id": channel_id,
                                "message_ts": msg.get("ts"),
                                "url": url,
                            },
                        )
                    )

        return signals, messages_scanned, collected

    def _extract_urls(self, text: str) -> List[str]:
        """Extract URLs from Slack message text."""
        urls = []
        # Slack wraps URLs in <url> or <url|label>
        for match in re.finditer(r"<(https?://[^|>]+)(?:\|[^>]*)?>", text):
            urls.append(match.group(1))
        # Also catch bare URLs
        for match in re.finditer(r"(?<![<|])https?://\S+", text):
            url = match.group(0).rstrip(">)")
            if url not in urls:
                urls.append(url)
        return urls

    def _classify_url(self, url: str) -> Optional[str]:
        """Classify a URL to an integration based on domain."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path = parsed.path.lower()
        except Exception:
            return None

        for integration_id, patterns in TOOL_PATTERNS.items():
            # Check domains
            for d in patterns.get("domains", []):
                if d in domain:
                    return integration_id
            # Check URL paths
            for p in patterns.get("url_paths", []):
                if p in path:
                    return integration_id

        return None

    def _deduplicate_signals(self, signals: List[Signal]) -> List[Signal]:
        """Deduplicate signals, keeping the highest confidence per integration+type."""
        best: Dict[str, Signal] = {}
        counts: Dict[str, int] = {}

        for signal in signals:
            key = f"{signal.integration_id}:{signal.signal_type}"
            counts[key] = counts.get(key, 0) + 1

            if key not in best or signal.confidence > best[key].confidence:
                best[key] = signal

        # Update metadata with counts
        deduped = []
        for key, signal in best.items():
            signal.metadata["occurrence_count"] = counts[key]
            deduped.append(signal)

        return deduped
