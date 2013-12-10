"""Model an algorithm as a list of functions.


Installation
------------

:py:mod:`algorithm` is available on `GitHub`_ and on `PyPI`_::

    $ pip install algorithm

We `test <https://travis-ci.org/gittip/algorithm.py>`_ against
Python 2.6, 2.7, 3.2, and 3.3.

:py:mod:`algorithm` is in the `public domain`_.


.. _GitHub: https://github.com/gittip/algorithm.py
.. _PyPI: https://pypi.python.org/pypi/algorithm
.. _public domain: http://creativecommons.org/publicdomain/zero/1.0/


Tutorial
--------

This module provides an abstraction for implementing arbitrary algorithms as a
list of functions that operate on a shared state dictionary. Algorithms defined
this way are easy to arbitrarily modify at run time, and they provide cascading
exception handling.

To get started, define an algorithm by defining a series of functions in a
Python file::

    def foo():
        return {'baz': 1}

    def bar():
        return {'buz': 2}

    def bloo(baz, buz):
        return {'sum': baz + buz)


Each function returns a :py:class:`dict`, which is used to update the state of
the current run of the algorithm. Names from the state dictionary are made
available to downstream functions via :py:mod:`dependency_injection`. Save this
file on your ``PYTHONPATH`` as ``blah_algorithm.py``. Now here's how to use it:

    >>> from algorithm import Algorithm
    >>> blah = Algorithm.from_dotted_name('blah_algorithm')


When you instantiate :py:class:`Algorithm` via the
:py:meth:`~Algorithm.from_dotted_name` constructor, you give it the dotted name
of a Python module. All of the functions defined in the module are loaded into
a list, in the order they're defined in the file:

    >>> blah.functions #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function bloo ...>]


Now you can use :py:func:`~Algorithm.run` to run the algorithm. You'll get back
a dictionary representing the algorithm's final state:

    >>> state = blah.run()
    >>> state['sum']
    3


Modifications and Exceptions
++++++++++++++++++++++++++++

Let's add two functions to the algorithm, to illustrate both algorithm
modification and exception handling. First let's define the functions:

    >>> def uh_oh(baz):
    ...     if baz == 2:
    ...         raise heck
    ...
    >>> def deal_with_it(exc_info):
    ...     print(exc_info[1])
    ...     return {'exc_info': None}
    ...


Now let's interpolate them into our algorithm. Let's put the ``uh_oh`` function between
``bar`` and ``bloo``:

    >>> blah.insert_before('bloo', uh_oh)
    >>> blah.functions #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function uh_oh ...>, <function bloo ...>]


Then let's add our exception handler at the end:

    >>> blah.insert_after('bloo', deal_with_it)
    >>> blah.functions #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>]


Just for kicks, let's remove the ``foo`` function while we're at it:

    >>> blah.remove('foo')
    >>> blah.functions #doctest: +ELLIPSIS
    [<function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>]


What happens when we run it? Since we no longer have the ``foo`` function
providing a value for ``bar``, we'll need to supply that using a keyword
argument to :py:func:`~Algorithm.run`:

    >>> state = blah.run(baz=2)
    global name 'heck' is not defined


The ``global name`` print statement came from our ``deal_with_it`` function.
Whenever a function raises an exception, like ``uh_oh`` did,
:py:class:`~Algorithm.run` captures the exception and populates an ``exc_info``
key in the current algorithm run state dictionary. While ``exc_info`` is not
``None``, any normal function is skipped, and only functions that ask for
``exc_info`` get called. So in our example ``deal_with_it`` got called, but
``bloo`` didn't, which is why there is no ``sum``:

    >>> 'sum' in state
    False


If we run without tripping the exception in ``uh_oh`` then we have ``sum`` at
the end:

    >>> blah.run(baz=5)['sum']
    7


API Reference
-------------

"""
from __future__ import absolute_import, division, print_function, unicode_literals

import opcode
import sys
import types
import traceback

from dependency_injection import resolve_dependencies


__version__ = '1.0.0rc1-dev'


if sys.version_info >= (3, 0, 0):

    _get_func_code = lambda f: f.__code__
    _get_func_name = lambda f: f.__name__

    def _transfer_func_name(to, from_):
        to.__name__ = from_.__name__

    def exec_(some_python, namespace):
        exec(some_python, namespace)
else:

    _get_func_code = lambda f: f.func_code
    _get_func_name = lambda f: f.func_name

    def _transfer_func_name(to, from_):
        to.func_name = from_.func_name

    def exec_(some_python, namespace):
        # Have to double-exec because the Python 2 form is SyntaxError in 3.
        exec("exec some_python in namespace")


class FunctionNotFound(KeyError):
    """Used when a function is not found in an algorithm function list (subclasses
    :py:exc:`KeyError`).
    """
    def __str__(self):
        return "The function '{0}' isn't in this algorithm.".format(*self.args)


class Algorithm(object):
    """Model an algorithm as a list of functions.

    :param functions: a sequence of functions in the order they are to be run
    :param bool raise_immediately: Whether to re-raise exceptions immediately.
        :py:class:`False` by default, this can only be set as a keyword argument

    Each function in your algorithm must return a mapping or :py:class:`None`.
    If it returns a mapping, the mapping will be used to update a state
    dictionary for the current run of the algorithm. Functions in the algorithm
    can use any name from the current state dictionary as a parameter, and the
    value will then be supplied dynamically via :py:mod:`dependency_injection`.
    See the :py:func:`run` method for details on exception handling.

    """

    functions = None        #: A list of functions comprising the algorithm.
    default_raise_immediately = False


    def __init__(self, *functions, **kw):
        self.default_raise_immediately = kw.pop('raise_immediately', False)
        if functions:
            try:
                _get_func_name(functions[0])
            except AttributeError:
                raise TypeError("Not a function: {}".format(repr(functions[0])))
        self.functions = list(functions)
        self.debug = DebugMethod(self)


    @classmethod
    def from_dotted_name(cls, dotted_name, **kw):
        """Construct a new instance from an algorithm definition module.

        :param dotted_name: the dotted name of a Python module containing an
            algorithm definition

        :param kw: keyword arguments are passed through to the default constructor

        An algorithm definition is a regular Python file. All functions defined
        in the file whose name doesn't begin with ``_`` are loaded into a list
        in the order they're defined in the file, and this list is passed to
        the default class constructor. See the `tutorial`_ for an example.

        """
        module = cls._load_module_from_dotted_name(dotted_name)
        functions = cls._load_functions_from_module(module)
        return cls(*functions, **kw)


    def __getitem__(self, name):
        """Return the function in the :py:attr:`functions` list named ``name``, or raise
        :py:exc:`FunctionNotFound`.

        >>> def foo(): pass
        >>> algo = Algorithm(foo)
        >>> algo['foo'] is foo
        True
        >>> algo['bar']
        Traceback (most recent call last):
          ...
        FunctionNotFound: The function 'bar' isn't in this algorithm.

        """
        func = None
        for candidate in self.functions:
            if _get_func_name(candidate) == name:
                func = candidate
                break
        if func is None:
            raise FunctionNotFound(name)
        return func


    def get_names(self):
        """Returns a list of the names of the functions in the :py:attr:`functions` list.
        """
        return [_get_func_name(f) for f in self.functions]


    def insert_after(self, name, newfunc):
        """Insert ``newfunc`` in the :py:attr:`functions` list after the function named
        ``name``, or raise :py:exc:`FunctionNotFound`.
        """
        self.insert_relative_to(name, newfunc, relative_position=1)


    def insert_before(self, name, newfunc):
        """Insert ``newfunc`` in the :py:attr:`functions` list before the function named
        ``name``, or raise :py:exc:`FunctionNotFound`.
        """
        self.insert_relative_to(name, newfunc, relative_position=0)


    def insert_relative_to(self, name, newfunc, relative_position):
        func = self[name]
        index = self.functions.index(func) + relative_position
        self.functions.insert(index, newfunc)


    def remove(self, name):
        """Remove the function named ``name`` from the :py:attr:`functions` list, or raise
        :py:exc:`FunctionNotFound`.
        """
        func = self[name]
        self.functions.remove(func)


    def run(self, _raise_immediately=None, _return_after=None, **state):
        """Run through the functions in the :py:attr:`functions` list.

        :param bool _raise_immediately: if not ``None``, will override any
            default for ``raise_immediately`` that was set in the constructor

        :param str _return_after: if not ``None``, return after calling the function
            with this name

        :param dict state: remaining keyword arguments are used for the initial
            state dictionary for this run of the algorithm

        :raises: :py:exc:`FunctionNotFound`, if there is no function named
            ``_return_after``

        :returns: a dictionary representing the final algorithm state

        The state dictionary is initialized with three items (their default
        values can be overriden using keyword arguments to :py:func:`run`):

         - ``algorithm`` - a reference to the parent :py:class:`Algorithm` instance
         - ``state`` - a circular reference to the state dictionary
         - ``exc_info`` - ``None``

        For each function in the :py:attr:`functions` list, we look at the
        function signature and compare it to the current value of ``exc_info``
        in the state dictionary. If ``exc_info`` is ``None`` then we skip any
        function that asks for ``exc_info``, and if ``exc_info`` is *not*
        ``None`` then we only call functions that *do* ask for it. The upshot
        is that any function that raises an exception will cause us to
        fast-forward to the next exception-handling function in the list.

        Here are some further notes on exception handling:

         - If a function provides a default value for ``exc_info``, then that
           function will be called whether or not there is an exception being
           handled.

         - You should return ``{'exc_info': None}`` to reset exception
           handling. We call :py:func:`sys.exc_clear` for you in this case.

         - As advised in the Python docs for :py:func:`sys.exc_info`, we avoid
           assigning the third item of the return value of that function, a
           traceback object, to a local variable. Instead, we replace it with a
           string representation of the traceback. Your handler should call
           :func:`sys.exc_info` directly if you need the full traceback object.

         - If ``exc_info`` is not ``None`` after all functions have been run,
           then we re-raise the current exception.

         - If ``raise_immediately`` evaluates to ``True`` (looking first at any
           per-call ``_raise_immediately`` and then at the instance default),
           then we re-raise any exception immediately instead of
           fast-forwarding to the next exception handler.

        """

        if _raise_immediately is None:
            _raise_immediately = self.default_raise_immediately

        if _return_after is not None:
            if _return_after not in self.get_names():
                raise FunctionNotFound(_return_after)

        if 'algorithm' not in state:    state['algorithm'] = self
        if 'state' not in state:        state['state'] = state
        if 'exc_info' not in state:     state['exc_info'] = None

        for function in self.functions:
            function_name = _get_func_name(function)
            try:
                deps = resolve_dependencies(function, state)
                have_exc_info = state['exc_info'] is not None
                if 'exc_info' in deps.signature.required and not have_exc_info:
                    pass    # Function wants exc_info but we don't have it.
                elif 'exc_info' not in deps.signature.parameters and have_exc_info:
                    pass    # Function doesn't want exc_info but we have it.
                else:
                    new_state = function(**deps.as_kwargs)
                    if new_state is not None:
                        if 'exc_info' in new_state:
                            if new_state['exc_info'] is None:
                                sys.exc_clear()
                        state.update(new_state)
            except:
                state['exc_info'] = sys.exc_info()[:2] + (traceback.format_exc().strip(),)
                if _raise_immediately:
                    raise

            if _return_after is not None and function_name == _return_after:
                break

        if state['exc_info'] is not None:
            raise

        return state


    # Helpers for loading from a file.
    # ================================

    @staticmethod
    def _load_module_from_dotted_name(dotted_name):
        class RootModule(object): pass
        module = RootModule()  # let's us use getattr to traverse down
        exec_('import {0}'.format(dotted_name), module.__dict__)
        for name in dotted_name.split('.'):
            module = getattr(module, name)
        return module


    @staticmethod
    def _load_functions_from_module(module):
        """Given a module object, return a list of functions from the module, sorted by lineno.
        """
        functions_with_lineno = []
        for name in dir(module):
            if name.startswith('_'):
                continue
            obj = getattr(module, name)
            if type(obj) != types.FunctionType:
                continue
            func = obj
            lineno = _get_func_code(func).co_firstlineno
            functions_with_lineno.append((lineno, func))
        functions_with_lineno.sort()
        return [func for lineno, func in functions_with_lineno]


# Debugging Helpers
# =================

class DebugMethod(object):
    """This provides a callable that also provides mapping access.
    """

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def __call__(self, function):
        """Given a function, set it up for debugging.
        """
        debugging_function = debug(function)
        for i, candidate in enumerate(self.algorithm.functions):
            if candidate is function:
                self.algorithm.functions[i] = debugging_function
        return debugging_function

    def debug_by_name(self, name):
        return self(self.algorithm[name])

    __getitem__ = debug_by_name


def debug(function):
    """Given a function, set a breakpoint immediately inside it.

    Okay! This is so fun. :-)

    The idea here is that you want to be able to debug an algorithm function,
    but it's inconvenient to get to the source in order to set a breakpoint. So
    what we do here is construct a new function object with modified bytecode
    (and attendent data structures). So this is basically a decorator, but it
    would be useless in situations where you could decorate a function (because
    then you have the source code in front of you and you could just insert the
    breakpoint yourself).

    >>> def foo(bar, baz):
    ...     print "Greetings, program!"
    ...
    >>> func = debug(foo)
    >>> func()
    blah

    This function is available as a static method on the Algorithm class,
    and also as a standalone function in the algorithm module. So you can
    `from algorithm import debug` and use it that way, or since you
    probably have an algorithm instance wherever you want to use this
    function, you can also use it like so:

    >>> blah = Algorithm.from_dotted_name('blah_algorithm')
    >>> blah.debug_by_name('blah_algorithm')

    """

    # Build bytecode for a set_trace call.
    # ====================================

    NOARG = object()

    codes = ( (b'LOAD_CONST', 0)
            , (b'LOAD_CONST', None)
            , (b'IMPORT_NAME', b'pdb')
            , (b'STORE_GLOBAL', b'pdb')
            , (b'LOAD_GLOBAL', b'pdb')
            , (b'LOAD_ATTR', b'set_trace')
            , (b'CALL_FUNCTION', 0)
            , (b'POP_TOP', NOARG)
             )

    new_names = function.__code__.co_names
    new_consts = function.__code__.co_consts
    new_code = b''
    addr_pad = 0

    for name, arg in codes:

        # This is the inverse of the subset of dis.disassemble needed to handle
        # our use case.

        addr_pad += 1
        op = opcode.opmap[name]
        new_code += chr(op)
        if op >= opcode.HAVE_ARGUMENT:
            addr_pad += 2
            if op in opcode.hasconst:
                if arg not in new_consts:
                    new_consts += (arg,)
                val = new_consts.index(arg)
            elif op in opcode.hasname:
                if arg not in new_names:
                    new_names += (arg,)
                val = new_names.index(arg)
            elif name == 'CALL_FUNCTION':
                val = arg  # number of args
            new_code += chr(val) + chr(0)


    # Finish inserting our new bytecode in front of the old.
    # ======================================================
    # Loop over old_code and append it to new_code, fixing up absolute jump
    # references along the way. Then fix up the line number table.

    old_code = function.__code__.co_code
    i = 0
    n = len(old_code)
    while i < n:
        c = old_code[i]
        op = ord(c)
        i += 1
        new_code += c
        if op >= opcode.HAVE_ARGUMENT:
            oparg = ord(old_code[i]) + ord(old_code[i+1])*256
            if op in opcode.hasjabs:
                oparg += addr_pad
            i += 2
            new_code += chr(oparg) + chr(0)

    old_lnotab = function.__code__.co_lnotab
    new_lnotab = (old_lnotab[:2] + chr(ord(old_lnotab[2]) + addr_pad) + old_lnotab[3:])


    # Now construct new code and function objects.
    # ============================================

    new_code = type(function.__code__)( function.__code__.co_argcount
                                      , function.__code__.co_nlocals
                                      , function.__code__.co_stacksize
                                      , function.__code__.co_flags

                                      , new_code
                                      , new_consts
                                      , new_names
                                      , function.__code__.co_varnames

                                      , function.__code__.co_filename
                                      , function.__code__.co_name
                                      , function.__code__.co_firstlineno
                                      , new_lnotab

                                      , function.__code__.co_freevars
                                      , function.__code__.co_cellvars
                                       )

    new_function = type(function)( new_code
                                 , function.func_globals
                                 , function.func_name
                                 , function.func_closure
                                  )

    return new_function


if __name__ == '__main__':
    import doctest
    doctest.testmod()
