"""Shared pytest fixtures and test configuration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set dummy env vars before any imports that need them
os.environ.setdefault("OPENAI_API_KEY", "sk-test-00000000000000000000000000000000")
os.environ.setdefault("PINECONE_API_KEY", "test-pinecone-key")
os.environ.setdefault("PINECONE_INDEX_NAME", "ions-energy-test")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("ENVIRONMENT", "test")
