# This is a support file for the debug test in tests.py.

def foo(state):
    state.baz = 1

def bar(state):
    state.buz = 2

def bloo(state):
    state.sum = state.baz + state.buz
