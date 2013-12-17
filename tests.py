from __future__ import absolute_import, division, print_function, unicode_literals

import sys

import traceback
from pytest import raises, yield_fixture
from algorithm import Algorithm, FunctionNotFound, PYTHON_2
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

def test_Algorithm_can_be_instantiated():
    def foo(): pass
    foo_algorithm = Algorithm(foo)
    assert foo_algorithm.functions == [foo]

def test_Algorithm_can_be_instantiated_with_from_dotted_name(sys_path):
    sys_path.mk(('foo/__init__.py', ''), ('foo/bar.py', 'def baz(): pass'))
    foo_algorithm = Algorithm.from_dotted_name('foo.bar')
    from foo.bar import baz
    assert foo_algorithm.functions == [baz]

def test_Algorithm_cant_be_instantiated_with_a_string():
    actual = raises(TypeError, Algorithm, 'foo.bar').value
    u = 'u' if sys.version_info < (3,) else ''
    assert str(actual) == "Not a function: {0}'foo.bar'".format(u)

def test_Algorithm_includes_imported_functions_and_the_order_is_screwy(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um
def blah(): pass
'''))
    foo_algorithm = Algorithm.from_dotted_name('foo.bar')
    import foo.bar, um
    assert foo_algorithm.functions == [um.um, foo.bar.baz, foo.bar.blah]

def test_Algorithm_ignores_functions_starting_with_underscore(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um as _um
def blah(): pass
'''))
    foo_algorithm = Algorithm.from_dotted_name('foo.bar')
    import foo.bar
    assert foo_algorithm.functions == [foo.bar.baz, foo.bar.blah]

def test_can_run_through_algorithm(sys_path):
    sys_path.mk(FOO_PY)
    foo_algorithm = Algorithm.from_dotted_name('foo')
    state = foo_algorithm.run(val=None)
    assert state == {'val': 3, 'exception': None, 'state': state, 'algorithm': foo_algorithm}

def test_can_stop_algorithm_after_a_certain_point(sys_path):
    sys_path.mk(FOO_PY)
    foo_algorithm = Algorithm.from_dotted_name('foo')
    state = foo_algorithm.run(val=None, _return_after='baz')
    assert state == {'val': 2, 'exception': None, 'state': state, 'algorithm': foo_algorithm}

def test_error_raised_if_we_try_to_return_after_an_unknown_function(sys_path):
    sys_path.mk(FOO_PY)
    foo_algorithm = Algorithm.from_dotted_name('foo')
    raises(FunctionNotFound, foo_algorithm.run, val=None, _return_after='blaaaaaah')

def test_inserted_algorithm_steps_run(sys_path):
    sys_path.mk(FOO_PY)
    foo_algorithm = Algorithm.from_dotted_name('foo')

    def biz(): return {'val': 4}

    foo_algorithm.insert_after('buz', biz)
    state = foo_algorithm.run(val=None)

    assert state == {'val': 4, 'exception': None, 'state': state, 'algorithm':foo_algorithm}


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
    foo_algorithm = Algorithm.from_dotted_name('foo')
    state = foo_algorithm.run()
    assert state == {'val': 666, 'exception': None, 'state': state, 'algorithm': foo_algorithm}

def test_exception_raises_if_uncleared(sys_path):
    sys_path.mk(EXCEPT)
    foo_algorithm = Algorithm.from_dotted_name('foo')
    foo_algorithm.remove('clear')
    raises(NameError, foo_algorithm.run)

def test_traceback_for_uncleared_exception_reaches_back_to_original_raise(sys_path):
    sys_path.mk(EXCEPT)
    foo_algorithm = Algorithm.from_dotted_name('foo')
    foo_algorithm.remove('clear')
    try:
        foo_algorithm.run()
    except:
        tb = traceback.format_exc()

    # We get an extra frame under Python 3, but what we don't want is not
    # enough frames.

    assert len(tb.splitlines()) == (8 if PYTHON_2 else 10)

def test_function_can_have_default_value_for_exception_to_be_always_called(sys_path):
    sys_path.mk(EXCEPT)
    foo_algorithm = Algorithm.from_dotted_name('foo')

    # Add a both-handling function.
    def both(exception=None):
        return {'exception': None, 'um': 'yeah'}
    foo_algorithm.insert_before('clear', both)

    # Exception case.
    assert foo_algorithm.run()['um'] == 'yeah'

    # Non-exception case.
    foo_algorithm.remove('bar')
    assert foo_algorithm.run()['um'] == 'yeah'

def test_exception_raises_immediately_if_told_to_via_constructor(sys_path):
    sys_path.mk(EXCEPT)
    foo_algorithm = Algorithm.from_dotted_name('foo', raise_immediately=True)
    foo_algorithm.remove('clear')
    raises(NameError, foo_algorithm.run)

def test_exception_raises_immediately_if_told_to_via_run_call(sys_path):
    sys_path.mk(EXCEPT)
    foo_algorithm = Algorithm.from_dotted_name('foo')
    foo_algorithm.remove('clear')
    raises(NameError, foo_algorithm.run, _raise_immediately=True)

def test_per_call_trumps_constructor_for_raise_immediately(sys_path):
    sys_path.mk(EXCEPT)
    foo_algorithm = Algorithm.from_dotted_name('foo', raise_immediately=True)
    foo_algorithm.remove('clear')
    raises(NameError, foo_algorithm.run, _raise_immediately=False)
