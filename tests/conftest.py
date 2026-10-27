"""Shared pytest fixtures for mnemosyne-mcp tests."""

import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    return tmp_path / "test_mnemosyne.db"
