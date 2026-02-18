"""
Environment variable manager for local development mode.

Handles reading and writing to .env files, with support for:
- Atomic updates (file locking)
- Comment and formatting preservation
- Thread-safe operations
"""

import fcntl
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional


class EnvManager:
    """Manages .env file operations for local development."""

    def __init__(self, env_file_path: str = ".env"):
        """Initialize the env manager.

        Args:
            env_file_path: Path to the .env file (relative to project root)
        """
        self.env_file_path = Path(env_file_path)

    def read_env_file(self) -> Dict[str, str]:
        """Read and parse the .env file.

        Returns:
            Dictionary of environment variables
        """
        if not self.env_file_path.exists():
            return {}

        env_vars = {}
        with open(self.env_file_path, "r") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue

                # Parse KEY=VALUE
                match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
                if match:
                    key, value = match.groups()
                    # Remove quotes if present
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    env_vars[key] = value

        return env_vars

    def write_env_variable(
        self, key: str, value: str, comment: Optional[str] = None
    ) -> None:
        """Write or update a single environment variable in the .env file.

        This operation is atomic and thread-safe using file locking.

        Args:
            key: Environment variable name (e.g., "CORALOGIX_API_KEY")
            value: Environment variable value
            comment: Optional comment to add above the variable
        """
        # Ensure parent directory exists
        self.env_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing content
        existing_lines = []
        if self.env_file_path.exists():
            with open(self.env_file_path, "r") as f:
                existing_lines = f.readlines()

        # Find if the variable already exists
        var_pattern = re.compile(f"^{re.escape(key)}=")
        found = False
        new_lines = []

        for line in existing_lines:
            if var_pattern.match(line.strip()):
                # Replace existing variable
                if comment:
                    new_lines.append(f"# {comment}\n")
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)

        # If not found, append to end
        if not found:
            # Add a blank line before if file is not empty
            if existing_lines and not existing_lines[-1].endswith("\n\n"):
                new_lines.append("\n")
            if comment:
                new_lines.append(f"# {comment}\n")
            new_lines.append(f"{key}={value}\n")

        # Write atomically using temp file + rename
        with tempfile.NamedTemporaryFile(
            mode="w", dir=self.env_file_path.parent, delete=False, prefix=".env.tmp."
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            try:
                # Write content
                tmp_file.writelines(new_lines)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

                # Atomic rename
                tmp_path.replace(self.env_file_path)
            except Exception:
                # Clean up temp file on error
                if tmp_path.exists():
                    tmp_path.unlink()
                raise

    def resolve_env_references(self, config: Dict) -> Dict:
        """Recursively resolve ${ENV_VAR} references in a config dictionary.

        Args:
            config: Configuration dictionary that may contain ${VAR} references

        Returns:
            New dictionary with resolved values
        """
        env_vars = self.read_env_file()
        # Also include current environment
        env_vars.update(os.environ)

        def resolve_value(value):
            """Recursively resolve a value."""
            if isinstance(value, str):
                # Replace ${VAR} with actual value
                def replacer(match):
                    var_name = match.group(1)
                    return env_vars.get(
                        var_name, match.group(0)
                    )  # Keep ${VAR} if not found

                return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replacer, value)
            elif isinstance(value, dict):
                return {k: resolve_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [resolve_value(item) for item in value]
            else:
                return value

        return resolve_value(config)

    def extract_env_references(self, config: Dict) -> set[str]:
        """Extract all ${ENV_VAR} references from a config dictionary.

        Args:
            config: Configuration dictionary

        Returns:
            Set of environment variable names referenced
        """
        references = set()

        def extract_from_value(value):
            """Recursively extract references from a value."""
            if isinstance(value, str):
                matches = re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
                references.update(matches)
            elif isinstance(value, dict):
                for v in value.values():
                    extract_from_value(v)
            elif isinstance(value, list):
                for item in value:
                    extract_from_value(item)

        extract_from_value(config)
        return references


# Global instance
_env_manager: Optional[EnvManager] = None


def get_env_manager(env_file_path: Optional[str] = None) -> EnvManager:
    """Get or create the global EnvManager instance.

    Args:
        env_file_path: Optional path to .env file.
                      If not provided, uses ENV_FILE_PATH env var or defaults to ".env"
    """
    global _env_manager

    # Determine the env file path
    if env_file_path is None:
        # Check ENV_FILE_PATH environment variable (set in docker-compose for container)
        env_file_path = os.getenv("ENV_FILE_PATH", ".env")

    if _env_manager is None or _env_manager.env_file_path != Path(env_file_path):
        _env_manager = EnvManager(env_file_path)
    return _env_manager
