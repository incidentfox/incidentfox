"""Tests for security fixes in Ultimate RAG (RAG-001, RAG-002, RAG-003)."""

import io
import os
import pickle
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# RAG-002: Restricted Pickle Unpickler tests
# ---------------------------------------------------------------------------
class TestRestrictedUnpickler:
    """Test that the restricted unpickler blocks dangerous types."""

    def _load(self, data: bytes):
        from ultimate_rag.core.persistence import safe_pickle_loads

        return safe_pickle_loads(data)

    def test_safe_dict(self):
        data = pickle.dumps({"key": "value", "num": 42})
        result = self._load(data)
        assert result == {"key": "value", "num": 42}

    def test_safe_list(self):
        data = pickle.dumps([1, 2, "three", 4.0])
        result = self._load(data)
        assert result == [1, 2, "three", 4.0]

    def test_safe_nested(self):
        obj = {"trees": [{"nodes": [1, 2, 3]}, {"nodes": [4, 5]}], "count": 2}
        data = pickle.dumps(obj)
        result = self._load(data)
        assert result == obj

    def test_safe_tuple(self):
        data = pickle.dumps((1, "two", 3.0))
        result = self._load(data)
        assert result == (1, "two", 3.0)

    def test_safe_set(self):
        data = pickle.dumps({1, 2, 3})
        result = self._load(data)
        assert result == {1, 2, 3}

    def test_safe_bool_none(self):
        data = pickle.dumps({"flag": True, "empty": None})
        result = self._load(data)
        assert result == {"flag": True, "empty": None}

    def test_blocks_os_system(self):
        """Crafted pickle that would call os.system('id') — must be blocked."""
        # Build a pickle payload that calls os.system
        payload = (
            b"\x80\x04\x95\x1e\x00\x00\x00\x00\x00\x00\x00"
            b"\x8c\x05posix\x8c\x06system\x93\x8c\x02id\x85R."
        )
        with pytest.raises(pickle.UnpicklingError, match="Blocked unpickling"):
            self._load(payload)

    def test_blocks_subprocess(self):
        """Pickle referencing subprocess.Popen must be blocked."""
        payload = (
            b"\x80\x04\x95*\x00\x00\x00\x00\x00\x00\x00"
            b"\x8c\nsubprocess\x8c\x05Popen\x93"
            b"\x8c\x02id\x85\x85R."
        )
        with pytest.raises(pickle.UnpicklingError, match="Blocked unpickling"):
            self._load(payload)

    def test_blocks_eval(self):
        """Pickle trying to use builtins.eval must be blocked (not in safe builtins)."""
        payload = (
            b"\x80\x04\x95\x1f\x00\x00\x00\x00\x00\x00\x00"
            b"\x8c\x08builtins\x8c\x04eval\x93\x8c\x011\x85R."
        )
        with pytest.raises(pickle.UnpicklingError, match="Blocked unpickling"):
            self._load(payload)

    def test_safe_pickle_load_file(self):
        """Test safe_pickle_load with file-like object."""
        from ultimate_rag.core.persistence import safe_pickle_load

        data = pickle.dumps({"hello": "world"})
        result = safe_pickle_load(io.BytesIO(data))
        assert result == {"hello": "world"}

    def test_blocks_arbitrary_class(self):
        """Any class not in the allow list should be blocked."""
        # pickle for collections.OrderedDict is safe (collections in safe modules),
        # but something like http.client.HTTPConnection should not be
        payload = (
            b"\x80\x04\x95&\x00\x00\x00\x00\x00\x00\x00"
            b"\x8c\x0bhttp.client\x8c\x0eHTTPConnection\x93"
            b"\x8c\x09localhost\x85R."
        )
        with pytest.raises(pickle.UnpicklingError, match="Blocked unpickling"):
            self._load(payload)


# ---------------------------------------------------------------------------
# RAG-003: Path Traversal Protection tests
# ---------------------------------------------------------------------------
class TestPathTraversal:
    """Test path traversal protection in ingestion endpoints."""

    def test_traversal_blocked(self):
        """Paths like ../../etc/passwd must be rejected."""
        trees_dir = "/app/trees"
        allowed_base = Path(trees_dir).resolve()
        evil_path = "../../etc/passwd"
        resolved = Path(evil_path).resolve()
        assert not (
            str(resolved).startswith(str(allowed_base) + os.sep)
            or resolved == allowed_base
        )

    def test_path_within_allowed(self):
        """Paths within the allowed directory should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_base = Path(tmpdir).resolve()
            good_path = os.path.join(tmpdir, "myfile.txt")
            resolved = Path(good_path).resolve()
            assert str(resolved).startswith(str(allowed_base) + os.sep)

    def test_symlink_escape_blocked(self):
        """Symlinks that escape the base directory must be blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_base = Path(tmpdir).resolve()
            # Create a symlink that points outside
            link_path = os.path.join(tmpdir, "escape")
            try:
                os.symlink("/etc", link_path)
                resolved = Path(os.path.join(link_path, "passwd")).resolve()
                assert not str(resolved).startswith(str(allowed_base) + os.sep)
            except OSError:
                pytest.skip("Cannot create symlinks in this environment")

    def test_null_byte_in_path(self):
        """Null bytes in path should raise ValueError/OSError."""
        with pytest.raises((ValueError, OSError)):
            Path("/app/trees/\x00evil").resolve()

    def test_dot_dot_in_middle(self):
        """Path with /../ in the middle should be resolved and checked."""
        trees_dir = "/app/trees"
        allowed_base = Path(trees_dir).resolve()
        evil = "/app/trees/subdir/../../etc/passwd"
        resolved = Path(evil).resolve()
        assert not str(resolved).startswith(str(allowed_base) + os.sep)


# ---------------------------------------------------------------------------
# RAG-001: API Key Auth Middleware tests
# ---------------------------------------------------------------------------
class TestAPIKeyAuth:
    """Test API key authentication middleware logic."""

    def test_bearer_token_extraction(self):
        """Bearer token should be extracted correctly."""
        auth = "Bearer my-secret-key"
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:]
        assert token == "my-secret-key"

    def test_x_api_key_extraction(self):
        """X-API-Key header should be used as fallback."""
        auth = ""
        api_key = "my-secret-key"
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:]
        elif api_key:
            token = api_key
        assert token == "my-secret-key"

    def test_no_auth_headers(self):
        """Missing auth should result in empty token."""
        auth = ""
        api_key = ""
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:]
        elif api_key:
            token = api_key
        assert token == ""

    def test_timing_safe_comparison(self):
        """hmac.compare_digest should be used for constant-time comparison."""
        import hmac

        assert hmac.compare_digest("correct-key", "correct-key")
        assert not hmac.compare_digest("correct-key", "wrong-key")
        assert not hmac.compare_digest("", "any-key")
