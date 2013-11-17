import sys

from pytest import raises, yield_fixture
from lifecycle import Lifecycle, FunctionNotFound
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

def test_Lifecycle_can_be_instantiated(sys_path):
    sys_path.mk(('foo/__init__.py', ''), ('foo/bar.py', 'def baz(): pass'))
    bar_lifecycle = Lifecycle('foo.bar')
    from foo.bar import baz
    assert list(bar_lifecycle) == [baz]

def test_Lifecycle_includes_imported_functions_and_the_order_is_screwy(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um
def blah(): pass
'''))
    bar_lifecycle = Lifecycle('foo.bar')
    import foo.bar, um
    assert list(bar_lifecycle) == [um.um, foo.bar.baz, foo.bar.blah]

def test_Lifecycle_ignores_functions_starting_with_underscore(sys_path):
    sys_path.mk( ('um.py', 'def um(): pass')
               , ('foo/__init__.py', '')
               , ('foo/bar.py', '''
def baz(): pass
from um import um as _um
def blah(): pass
'''))
    bar_lifecycle = Lifecycle('foo.bar')
    import foo.bar
    assert list(bar_lifecycle) == [foo.bar.baz, foo.bar.blah]

def test_can_run_through_lifecycle(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_lifecycle = Lifecycle('foo')
    state = bar_lifecycle.run({'val': None})
    assert state == {'val': 3, 'exc_info': None, 'state': state, 'lifecycle': bar_lifecycle}

def test_can_run_through_lifecycle_to_a_certain_point(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_lifecycle = Lifecycle('foo')
    state = bar_lifecycle.run({'val': None}, through='baz')
    assert state == {'val': 2, 'exc_info': None, 'state': state, 'lifecycle': bar_lifecycle}

def test_error_raised_if_we_try_to_run_through_an_unknown_function(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_lifecycle = Lifecycle('foo')
    raises(FunctionNotFound, bar_lifecycle.run, {'val': None}, through='blaaaaaah')


def test_inserted_lifecycle_steps_run(sys_path):
    sys_path.mk(('foo.py', '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''))
    bar_lifecycle = Lifecycle('foo')

    def biz(): return {'val': 4}

    bar_lifecycle.insert_after('buz', biz)
    state = bar_lifecycle.run({'val': None})

    assert state == {'val': 4, 'exc_info': None, 'state': state, 'lifecycle':bar_lifecycle}


# Lifecycle decorators
# ====================

from lifecycle import by_lambda

FOO_PY = '''
def bar(): return {'val': 1}
def baz(): return {'val': 2}
def buz(): return {'val': 3}
'''

def test_filter_a_lifecycle(sys_path):
    sys_path.mk(('foo.py', FOO_PY))
    bar_lifecycle = Lifecycle('foo')

    @by_lambda(lambda: True)
    def biz():
        print("in biz")
        return {'val': 4}

    bar_lifecycle.insert_after('buz', biz)

    state = bar_lifecycle.run({'val': None})
    assert state == {'val': 4, 'exc_info': None, 'state': state, 'lifecycle': bar_lifecycle}
