"""Two threads importing openloops at once must both get it whole (_equerry#34).

The package's ``__init__`` used to import ``openloops.tools``, which imports the package's
own submodules. A thread importing ``openloops.tools`` (as crowsnest does) while another
imported ``openloops.obligations`` deadlocked on the module locks, and CPython broke the
deadlock by handing one of them a half-built module: ``cannot import name 'ls'``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

RACE = textwrap.dedent(
    """
    import threading
    barrier, errors = threading.Barrier(3), []

    def load(statement):
        barrier.wait()
        try:
            exec(statement, {})
        except Exception as exc:
            errors.append(repr(exc))

    statements = ("from openloops.tools import show", "from openloops.obligations import owed",
                  "import openloops")
    threads = [threading.Thread(target=load, args=(s,)) for s in statements]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    from openloops import ls, show, status
    print(errors or "ok")
    """
)


def test_concurrent_imports_in_a_fresh_interpreter_all_succeed():
    for _ in range(3):  # the race was deterministic, but a fresh process each time is cheap
        out = subprocess.run([sys.executable, "-c", RACE], capture_output=True, text=True, timeout=60)
        assert out.returncode == 0 and out.stdout.strip() == "ok", out.stdout + out.stderr
