"""Pytest configuration and environment fixtures."""
from pathlib import Path
import _pytest.pathlib

# Safely handle Windows symlink cleanup without elevated permissions
_orig_cleanup = _pytest.pathlib.cleanup_dead_symlinks


def _safe_cleanup(root):
    try:
        _orig_cleanup(root)
    except (PermissionError, OSError):
        pass


_pytest.pathlib.cleanup_dead_symlinks = _safe_cleanup
