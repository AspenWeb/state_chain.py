#!/bin/sh -eu
python state_chain.py  # doctests
py.test -v tests.py
pyflakes state_chain.py tests.py
