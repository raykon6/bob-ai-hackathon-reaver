"""Test-wide setup. pytest imports conftest.py BEFORE any test module, so these
environment variables are in place before app.audit reads TRIAGE_DB_PATH at import
time — regardless of which test file happens to run first."""
import os
import shutil
import tempfile

import pytest

_TMP_DIR = tempfile.mkdtemp(prefix="triage-tests-")
os.environ["TRIAGE_OFFLINE"] = "1"                       # never call watsonx in tests
os.environ["TRIAGE_DB_PATH"] = os.path.join(_TMP_DIR, "audit.db")  # never touch the real log


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_dir():
    yield
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
