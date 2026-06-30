"""Tests unitaires pour sandbox.py — Genesis Protocol P4."""
import pytest
from pathlib import Path
from sandbox import check_sandbox, is_safe_path, create_backup, sandbox_write, SANDBOX


class TestSandbox:
    """Isolation et sécurité pour écriture fichiers."""

    def test_check_sandbox_valid(self):
        """Chemin valide dans le sandbox → OK."""
        valid = str(SANDBOX / "test.txt")
        result = check_sandbox(valid)
        assert result.is_relative_to(SANDBOX)

    def test_check_sandbox_invalid(self):
        """Chemin hors sandbox → PermissionError."""
        with pytest.raises(PermissionError, match="hors sandbox"):
            check_sandbox("/etc/passwd")

    def test_is_safe_path_valid(self):
        """is_safe_path avec chemin valide → True."""
        assert is_safe_path(str(SANDBOX / "test.txt")) is True

    def test_is_safe_path_invalid(self):
        """is_safe_path avec chemin invalide → False."""
        assert is_safe_path("/etc/passwd") is False

    def test_sandbox_write(self, tmp_path, monkeypatch):
        """Écriture dans sandbox + backup."""
        monkeypatch.setattr("sandbox.SANDBOX", tmp_path)
        test_file = tmp_path / "hello.txt"
        sandbox_write(test_file, "Hello, World!")
        assert test_file.exists()
        assert test_file.read_text() == "Hello, World!"

    def test_sandbox_write_hors_sandbox(self, tmp_path, monkeypatch):
        """Écriture hors sandbox → PermissionError."""
        monkeypatch.setattr("sandbox.SANDBOX", tmp_path)
        with pytest.raises(PermissionError, match="hors sandbox"):
            sandbox_write(Path("/etc/test.txt"), "test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
