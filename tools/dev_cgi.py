#!/usr/bin/env python3
"""api.cgi for the local preview (tools/devserver.py): the real request handling without DSM.

There is no DSM session on a development machine, so the login and administrator checks are
replaced here. The package itself has no switch for that: this file is not part of it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "lib"))

from synetscan import cgi_main  # noqa: E402

cgi_main.authenticate = lambda: "dev"
cgi_main.is_admin = lambda user: True
cgi_main.VAR_DIR = os.environ["SYNETSCAN_VAR"]
cgi_main.main()
