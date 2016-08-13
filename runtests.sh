#!/bin/sh -eu
python algorithm.py  # doctests
py.test -v tests.py
pyflakes algorithm.py tests.py
