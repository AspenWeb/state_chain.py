from types import SimpleNamespace
import sys
import traceback
from unittest.mock import patch

from filesystem_tree import FilesystemTree
from pytest import raises, yield_fixture

from state_chain import StateChain, FunctionNotFound, IncompleteModification


# fixtures
# ========

@yield_fixture
def fs():
    fs = FilesystemTree()
    yield fs
    fs.remove()

@yield_fixture
def module_scrubber():
    before = set(sys.modules.keys())
    yield
    after = set(sys.modules.keys())
    for name in after - before:
        del sys.modules[name]


# tests
# =====

def val1(state):
    state.val = 1

def val2(state):
    state.val = 2

def val3(state):
    state.val = 3

val_chain = StateChain(SimpleNamespace, functions=[val1, val2, val3])

def val4(state):
    state.val = 4

def test_can_run_through_state_chain():
    state = val_chain.run(SimpleNamespace())
    assert state.__dict__ == {'val': 3, 'exception': None}

def test_can_stop_state_chain_after_a_certain_point():
    state = val_chain.run(return_after='val2')
    assert state.__dict__ == {'val': 2, 'exception': None}

def test_error_raised_if_we_try_to_return_after_an_unknown_function():
    with raises(FunctionNotFound):
        val_chain.run(return_after='nonexistent')

def test_inserted_state_chain_steps_run():
    chain = val_chain.copy()
    chain.add(val4, position=chain.after('val3'))
    state = chain.run()
    assert state.__dict__ == {'val': 4, 'exception': None}

def test_modify_method():
    chain = (
        val_chain.copy().modify()
        .debug('val1', exception='required')
        .drop('val2')
        .add(val3, exception='accepted')
        .add(val4)
        .end()
    )
    state = chain.run()
    assert state.val == 4

def test_modify_method_raises_IncompleteModification():
    with raises(IncompleteModification):
        val_chain.copy().modify().add('val2').drop('val1').end()


# Exception Handling
# ==================

def assert_false(state):
    assert False

def clear_exception(state):
    state.exception = None

def dont_call_me(state):
    raise Exception("I said don't call me!")

def test_exception_handlers_are_skipped_when_there_is_no_exception():
    chain = StateChain(SimpleNamespace)
    chain.add(dont_call_me, exception='required')
    chain.add(assert_false)
    chain.add(clear_exception, exception='required')
    chain.add(dont_call_me, exception='required')
    chain.run()

def test_exc_info_is_available_during_exception_handling():
    def check_exc_info(state):
        assert sys.exc_info()[1] is state.exception
        state.exception = None
    chain = StateChain(SimpleNamespace)
    chain.add(assert_false)
    chain.add(check_exc_info, exception='required')
    chain.run()

class Heck(Exception):
    pass

foo_chain = StateChain(SimpleNamespace)

@foo_chain.add
def bar(state):
    raise Heck()

@foo_chain.add
def baz(state):
    state.val = 42

@foo_chain.add(exception='required')
def clear(state):
    state.val = 666
    state.exception = None

def test_exception_fast_forwards():
    state = foo_chain.run()
    assert state.__dict__ == {'val': 666, 'exception': None}

def test_exception_raises_if_uncleared():
    chain = foo_chain.copy()
    chain.remove('clear')
    with raises(Heck):
        chain.run()

def test_traceback_for_uncleared_exception_reaches_back_to_original_raise():
    chain = foo_chain.copy()
    chain.remove('clear')
    try:
        chain.run()
    except Exception:
        tb = traceback.format_exc()
    lines = tb.splitlines()
    assert lines[-1] == 'tests.Heck'
    assert lines[-2].strip() == 'raise Heck()'

def test_function_can_have_default_value_for_exception_to_be_always_called():
    chain = foo_chain.copy()

    # Add a both-handling function.
    def both(state):
        state.exception = None
        state.um = 'yeah'
    chain.add(both, exception='accepted', position=chain.before('clear'))

    # Exception case.
    assert chain.run().um == 'yeah'

    # Non-exception case.
    chain.remove('bar')
    assert chain.run().um == 'yeah'

def test_exception_raises_immediately_if_told_to_via_constructor():
    chain = foo_chain.copy()
    chain.raise_immediately = True
    chain.remove('clear')
    with raises(Heck):
        chain.run()

def test_exception_raises_immediately_if_told_to_via_run_call():
    chain = foo_chain.copy()
    chain.remove('clear')
    with raises(Heck):
        chain.run(raise_immediately=True)

def test_per_call_trumps_constructor_for_raise_immediately():
    chain = foo_chain.copy()
    chain.remove('clear')
    with raises(Heck):
        chain.run(raise_immediately=False)


# debug
# =====

def test_debug_method():
    def set_trace():
        set_trace.call_count += 1
        from inspect import stack
        frameinfo = stack()[1]
        assert frameinfo.filename.endswith('blah_state_chain.py')
        assert frameinfo.lineno == 6

    set_trace.call_count = 0
    from blah_state_chain import foo, bar, bloo
    blah = StateChain(SimpleNamespace, functions=[foo, bar, bloo])
    blah.debug('bar')
    with patch('pdb.set_trace', set_trace):
        state = blah.run()
    assert set_trace.call_count == 1
    assert state.baz == 1
    assert state.buz == 2
    assert state.sum == 3
