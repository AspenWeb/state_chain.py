from __future__ import absolute_import, division, print_function, unicode_literals

import sys

from pytest import raises, yield_fixture
from algorithm import Algorithm, FunctionNotFound
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


# tests
# =====

def test_Algorithm_can_be_instantiated(sys_path):
    sys_path.mk(('foo/__init__.py', ''), ('foo/bar.py', 'def baz(): pass'))
    bar_algorithm = Algorithm('foo.bar')
    from foo.bar import baz
    assert list(bar_algorithm) == [baz]

def test_Algorithm_includes_imported_functions_and_the_order_is_screwy(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um
def blah(): pass
'''))
    bar_algorithm = Algorithm('foo.bar')
    import foo.bar, um
    assert list(bar_algorithm) == [um.um, foo.bar.baz, foo.bar.blah]

def test_Algorithm_ignores_functions_starting_with_underscore(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um as _um
def blah(): pass
'''))
    bar_algorithm = Algorithm('foo.bar')
    import foo.bar
    assert list(bar_algorithm) == [foo.bar.baz, foo.bar.blah]

def test_can_run_through_algorithm(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_algorithm = Algorithm('foo')
    state = bar_algorithm.run(val=None)
    assert state == {'val': 3, 'exc_info': None, 'state': state, 'algorithm': bar_algorithm}

def test_can_run_through_algorithm_to_a_certain_point(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_algorithm = Algorithm('foo')
    state = bar_algorithm.run(val=None, _through='baz')
    assert state == {'val': 2, 'exc_info': None, 'state': state, 'algorithm': bar_algorithm}

def test_error_raised_if_we_try_to_run_through_an_unknown_function(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_algorithm = Algorithm('foo')
    raises(FunctionNotFound, bar_algorithm.run, {'val': None}, through='blaaaaaah')


def test_inserted_algorithm_steps_run(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_algorithm = Algorithm('foo')

    def biz(): return {'val': 4}

    bar_algorithm.insert_after('buz', biz)
    state = bar_algorithm.run(val=None)

    assert state == {'val': 4, 'exc_info': None, 'state': state, 'algorithm':bar_algorithm}
