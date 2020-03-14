#!/bin/sh -eu
python -m doctest state_chain.py
py.test -v tests.py
pyflakes state_chain.py tests.py
