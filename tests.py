# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

import sys

import traceback
from pytest import raises, yield_fixture
from state_chain import StateChain, FunctionNotFound
from filesystem_tree import FilesystemTree


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

@yield_fixture
def sys_path(fs, module_scrubber):
    sys.path.insert(0, fs.root)
    yield fs
    sys.path = sys.path[1:]

FOO_PY = ('foo.py', '''\
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
''')


# tests
# =====

def test_StateChain_can_be_instantiated():
    def foo(): pass
    assert StateChain(foo).functions == [foo]

def test_StateChain_can_be_instantiated_with_from_dotted_name(sys_path):
    sys_path.mk(('foo/__init__.py', ''), ('foo/bar.py', 'def baz(): pass'))
    chain = StateChain.from_dotted_name('foo.bar')
    from foo.bar import baz
    assert chain.functions == [baz]

def test_StateChain_cant_be_instantiated_with_a_string():
    actual = raises(TypeError, StateChain, 'foo.bar').value
    u = 'u' if sys.version_info < (3,) else ''
    assert str(actual) == "Not a function: {0}'foo.bar'".format(u)

def test_StateChain_includes_imported_functions_and_the_order_is_screwy(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um
def blah(): pass
'''))
    chain = StateChain.from_dotted_name('foo.bar')
    import foo.bar, um
    assert chain.functions == [um.um, foo.bar.baz, foo.bar.blah]

def test_StateChain_ignores_functions_starting_with_underscore(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um as _um
def blah(): pass
'''))
    chain = StateChain.from_dotted_name('foo.bar')
    import foo.bar
    assert chain.functions == [foo.bar.baz, foo.bar.blah]

def test_can_run_through_state_chain(sys_path):
    sys_path.mk(FOO_PY)
    chain = StateChain.from_dotted_name('foo')
    state = chain.run(val=None)
    assert state == {'val': 3, 'exception': None, 'state': state, 'chain': chain}

def test_can_stop_state_chain_after_a_certain_point(sys_path):
    sys_path.mk(FOO_PY)
    chain = StateChain.from_dotted_name('foo')
    state = chain.run(val=None, _return_after='baz')
    assert state == {'val': 2, 'exception': None, 'state': state, 'chain': chain}

def test_error_raised_if_we_try_to_return_after_an_unknown_function(sys_path):
    sys_path.mk(FOO_PY)
    chain = StateChain.from_dotted_name('foo')
    raises(FunctionNotFound, chain.run, val=None, _return_after='blaaaaaah')

def test_inserted_state_chain_steps_run(sys_path):
    sys_path.mk(FOO_PY)
    chain = StateChain.from_dotted_name('foo')

    def biz(): return {'val': 4}

    chain.insert_after('buz', biz)
    state = chain.run(val=None)

    assert state == {'val': 4, 'exception': None, 'state': state, 'chain': chain}


# Exception Handling
# ==================

EXCEPT = ('foo.py', '''

    def bar():
        raise heck

    def baz():
        return {'val': 42}

    def clear(exception):
        return {'val': 666, 'exception': None}

''')

def test_exception_fast_forwards(sys_path):
    sys_path.mk(EXCEPT)
    chain = StateChain.from_dotted_name('foo')
    state = chain.run()
    assert state == {'val': 666, 'exception': None, 'state': state, 'chain': chain}

def assert_false():
    assert False

def clear_exception(state, exception):
    state['exception'] = None

def dont_call_me(exception):
    raise Exception("I said don't call me!")

def test_exception_handlers_are_skipped_when_there_is_no_exception(sys_path):
    StateChain(dont_call_me, assert_false, clear_exception, dont_call_me).run()

def test_exc_info_is_available_during_exception_handling(sys_path):
    def check_exc_info(exception):
        assert sys.exc_info()[1] is exception
        return {'exception': None}
    StateChain(assert_false, check_exc_info).run()

def test_exception_raises_if_uncleared(sys_path):
    sys_path.mk(EXCEPT)
    chain = StateChain.from_dotted_name('foo')
    chain.remove('clear')
    raises(NameError, chain.run)

def test_traceback_for_uncleared_exception_reaches_back_to_original_raise(sys_path):
    sys_path.mk(EXCEPT)
    chain = StateChain.from_dotted_name('foo')
    chain.remove('clear')
    try:
        chain.run()
    except:
        tb = traceback.format_exc()
    lines = tb.splitlines()
    assert lines[-1][:11] == 'NameError: '
    assert "'heck'" in lines[-1]
    assert len(lines) == 12, tb

def test_function_can_have_default_value_for_exception_to_be_always_called(sys_path):
    sys_path.mk(EXCEPT)
    chain = StateChain.from_dotted_name('foo')

    # Add a both-handling function.
    def both(exception=None):
        return {'exception': None, 'um': 'yeah'}
    chain.insert_before('clear', both)

    # Exception case.
    assert chain.run()['um'] == 'yeah'

    # Non-exception case.
    chain.remove('bar')
    assert chain.run()['um'] == 'yeah'

def test_exception_raises_immediately_if_told_to_via_constructor(sys_path):
    sys_path.mk(EXCEPT)
    chain = StateChain.from_dotted_name('foo', raise_immediately=True)
    chain.remove('clear')
    raises(NameError, chain.run)

def test_exception_raises_immediately_if_told_to_via_run_call(sys_path):
    sys_path.mk(EXCEPT)
    chain = StateChain.from_dotted_name('foo')
    chain.remove('clear')
    raises(NameError, chain.run, _raise_immediately=True)

def test_per_call_trumps_constructor_for_raise_immediately(sys_path):
    sys_path.mk(EXCEPT)
    chain = StateChain.from_dotted_name('foo', raise_immediately=True)
    chain.remove('clear')
    raises(NameError, chain.run, _raise_immediately=False)
