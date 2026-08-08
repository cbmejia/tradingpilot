# TradePilot AI — shared pytest setup.
#
# In plain terms: database/database.py picks its database file the moment
# it's first imported (from the DATABASE_URL environment variable, or
# database/tradepilot.db by default). Whichever test file imports it
# first — directly or indirectly, e.g. by importing backend.main — locks
# that choice in for the whole test run, since Python only imports a
# module once per process.
#
# pytest always loads conftest.py before it imports any test file, so
# this is the one place we can guarantee runs before that first import
# happens. Setting DATABASE_URL here means the real database/tradepilot.db
# is never touched by the test suite, even indirectly (e.g. by the
# FastAPI app's startup step, which calls init_db() with no database
# override of its own).

import os
import tempfile

_test_db_fd, _test_db_path = tempfile.mkstemp(prefix="tradepilot_test_", suffix=".db")
os.close(_test_db_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_test_db_path}")
