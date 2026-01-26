"""Tests for configuration management."""

import pytest
from ai_agent.core.config import Config, LoggingConfig, OpenAIConfig
from pydantic import ValidationError


class TestOpenAIConfig:
    def test_default_config(self):
        """Test default OpenAI configuration."""
        config = OpenAIConfig(api_key="test-key")
        assert config.model == "gpt-4"
        assert config.temperature == 0.7
        assert config.max_tokens == 4000

    def test_custom_temperature(self):
        """Test custom temperature within valid range."""
        config = OpenAIConfig(api_key="test-key", temperature=0.5)
        assert config.temperature == 0.5

    def test_invalid_temperature(self):
        """Test that invalid temperature raises error."""
        with pytest.raises(ValidationError):
            OpenAIConfig(api_key="test-key", temperature=3.0)


class TestLoggingConfig:
    def test_default_logging(self):
        """Test default logging configuration."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.format == "json"

    def test_valid_log_level(self):
        """Test valid log level."""
        config = LoggingConfig(level="DEBUG")
        assert config.level == "DEBUG"

    def test_invalid_log_level(self):
        """Test invalid log level raises error."""
        with pytest.raises(ValidationError):
            LoggingConfig(level="INVALID")


class TestConfig:
    def test_minimal_config(self):
        """Test minimal valid configuration."""
        config = Config(openai=OpenAIConfig(api_key="test-key"))
        assert config.environment == "development"
        assert not config.debug

    def test_validation_missing_api_key(self):
        """Test that missing OpenAI key is caught."""
        config = Config(openai=OpenAIConfig(api_key=""))
        errors = config.validate_required_config()
        assert len(errors) > 0
        assert any("api key" in err.lower() for err in errors)
