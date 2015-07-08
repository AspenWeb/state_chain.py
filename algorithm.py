"""Model an algorithm as a list of functions and shared state.

This module provides an abstraction for implementing arbitrary algorithms as a
list of functions that operate on a shared state dictionary. Algorithms defined
this way are easy to arbitrarily modify at run time, and they provide cascading
exception handling.

Installation
------------

:py:mod:`algorithm` is available on `GitHub`_ and on `PyPI`_::

    $ pip install algorithm

We `test <https://travis-ci.org/gittip/algorithm.py>`_ against
Python 2.6, 2.7, 3.2, and 3.3.

:py:mod:`algorithm` is MIT-licensed.


.. _GitHub: https://github.com/gittip/algorithm.py
.. _PyPI: https://pypi.python.org/pypi/algorithm


Tutorial
--------
The algorithm model is a list of functions that are executed in
defined order and update algorithm state stored in `state` dictionary.

To get started, define some functions:

    >>> def foo():
    ...     return {'baz': 1}
    ...
    >>> def bar():
    ...     return {'buz': 2}
    ...
    >>> def bloo(baz, buz):
    ...     return {'sum': baz + buz}
    ...


Each function returns a :py:class:`dict`, which updates the state of
the current run of the algorithm. Parameters for every function are
automatically fetched from `state` dictionary, using their names as
a key. This is done by :py:mod:`dependency_injection` module.

Now
make an :py:class:`Algorithm` object:

    >>> from algorithm import Algorithm
    >>> blah = Algorithm(foo, bar, bloo)


The functions you passed to the constructor are loaded into a list:

    >>> blah.functions          #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function bloo ...>]


Now you can use :py:func:`~Algorithm.run` to run the algorithm. You'll get back
a dictionary representing the algorithm's final state:

    >>> state = blah.run()
    >>> state['sum']
    3

Okay!


Modifying an Algorithm
++++++++++++++++++++++

Let's add two functions to the algorithm. First let's define the functions:

    >>> def uh_oh(baz):
    ...     if baz == 2:
    ...         raise heck
    ...
    >>> def deal_with_it(exception):
    ...     print("I am dealing with it!")
    ...     return {'exception': None}
    ...


Now let's interpolate them into our algorithm. Let's put the ``uh_oh`` function between
``bar`` and ``bloo``:

    >>> blah.insert_before('bloo', uh_oh)
    >>> blah.functions      #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function uh_oh ...>, <function bloo ...>]


Then let's add our exception handler at the end:

    >>> blah.insert_after('bloo', deal_with_it)
    >>> blah.functions      #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>]


Just for kicks, let's remove the ``foo`` function while we're at it:

    >>> blah.remove('foo')
    >>> blah.functions      #doctest: +ELLIPSIS
    [<function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>]


If you're making extensive changes to an algorithm, you should feel free to
directly manipulate the list of functions, rather than using the more
cumbersome :py:meth:`~algorithm.Algorithm.insert_before`,
:py:meth:`~algorithm.Algorithm.insert_after`, and
:py:meth:`~algorithm.Algorithm.remove` methods. We could have achieved the same
result like so:

    >>> blah.functions = [ blah['bar']
    ...                  , uh_oh
    ...                  , blah['bloo']
    ...                  , deal_with_it
    ...                   ]
    >>> blah.functions      #doctest: +ELLIPSIS
    [<function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>]


Either way, what happens when we run it? Since we no longer have the ``foo``
function providing a value for ``bar``, we'll need to supply that using a
keyword argument to :py:func:`~Algorithm.run`:

    >>> state = blah.run(baz=2)
    I am dealing with it!


Exception Handling
++++++++++++++++++

Whenever a function raises an exception, like ``uh_oh`` did in the example
above, :py:class:`~Algorithm.run` captures the exception and populates an
``exception`` key in the current algorithm run state dictionary. While
``exception`` is not ``None``, any normal function is skipped, and only
functions that ask for ``exception`` get called. It's like a fast-forward. So
in our example ``deal_with_it`` got called, but ``bloo`` didn't, which is why
there is no ``sum``:

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

import collections
import opcode
import sys
import types

from dependency_injection import resolve_dependencies


__version__ = '1.0.0-dev'
PYTHON_2 = sys.version_info < (3, 0, 0)


if PYTHON_2:
    def exec_(some_python, namespace):
        # Have to double-exec because the Python 2 form is SyntaxError in 3.
        exec("exec some_python in namespace")
else:
    def exec_(some_python, namespace):
        exec(some_python, namespace)


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

    START = -1
    END = -2


    def __init__(self, *functions, **kw):
        self.default_raise_immediately = kw.pop('raise_immediately', False)
        if functions:
            if not isinstance(functions[0], collections.Callable):
                raise TypeError("Not a function: {0}".format(repr(functions[0])))
        self.functions = list(functions)
        self.debug = _DebugMethod(self)


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
         - ``exception`` - ``None``

        For each function in the :py:attr:`functions` list, we look at the
        function signature and compare it to the current value of ``exception``
        in the state dictionary. If ``exception`` is ``None`` then we skip any
        function that asks for ``exception``, and if ``exception`` is *not*
        ``None`` then we only call functions that *do* ask for it. The upshot
        is that any function that raises an exception will cause us to
        fast-forward to the next exception-handling function in the list.

        Here are some further notes on exception handling:

         - If a function provides a default value for ``exception``, then that
           function will be called whether or not there is an exception being
           handled.

         - You should return ``{'exception': None}`` to reset exception
           handling. Under Python 2 we will call ``sys.exc_clear`` for you
           (under Python 3 exceptions are cleared automatically at the end of
           except blocks).

         - If ``exception`` is not ``None`` after all functions have been run,
           then we re-raise it.

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
        if 'exception' not in state:    state['exception'] = None

        for function in self.functions:
            function_name = function.__name__
            try:
                deps = resolve_dependencies(function, state)
                have_exception = state['exception'] is not None
                if 'exception' in deps.signature.required and not have_exception:
                    pass    # Function wants exception but we don't have it.
                elif 'exception' not in deps.signature.parameters and have_exception:
                    pass    # Function doesn't want exception but we have it.
                else:
                    new_state = function(**deps.as_kwargs)
                    if new_state is not None:
                        if PYTHON_2:
                            if 'exception' in new_state:
                                if new_state['exception'] is None:
                                    sys.exc_clear()
                        state.update(new_state)
            except:
                ExceptionClass, exception = sys.exc_info()[:2]
                state['exception'] = exception
                if _raise_immediately:
                    raise

            if _return_after is not None and function_name == _return_after:
                break

        if state['exception'] is not None:
            if PYTHON_2:

                # Under Python 2, raising state['exception'] means the
                # traceback stops at this reraise. We want the traceback to go
                # back to where the exception was first raised, and a naked
                # raise will reraise the current exception.

                raise

            else:

                # Under Python 3, exceptions are cleared at the end of the
                # except block, meaning we have no current exception to reraise
                # here. Thankfully, the traceback off this reraise will show
                # back to the original exception.

                raise state['exception']

        return state


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
            if candidate.__name__ == name:
                func = candidate
                break
        if func is None:
            raise FunctionNotFound(name)
        return func


    def get_names(self):
        """Returns a list of the names of the functions in the :py:attr:`functions` list.
        """
        return [f.__name__ for f in self.functions]


    def insert_before(self, name, *newfuncs):
        """Insert ``newfuncs`` in the :py:attr:`functions` list before the function named
        ``name``, or raise :py:exc:`FunctionNotFound`.

        >>> def foo(): pass
        >>> algo = Algorithm(foo)
        >>> def bar(): pass
        >>> algo.insert_before('foo', bar)
        >>> algo.get_names()
        ['bar', 'foo']
        >>> def baz(): pass
        >>> algo.insert_before('foo', baz)
        >>> algo.get_names()
        ['bar', 'baz', 'foo']
        >>> def bal(): pass
        >>> algo.insert_before(Algorithm.START, bal)
        >>> algo.get_names()
        ['bal', 'bar', 'baz', 'foo']
        >>> def bah(): pass
        >>> algo.insert_before(Algorithm.END, bah)
        >>> algo.get_names()
        ['bal', 'bar', 'baz', 'foo', 'bah']


        """
        if name == self.START:
            i = 0
        elif name == self.END:
            i = len(self.functions)
        else:
            i = self.functions.index(self[name])
        self.functions[i:i] = newfuncs


    def insert_after(self, name, *newfuncs):
        """Insert ``newfuncs`` in the :py:attr:`functions` list after the function named
        ``name``, or raise :py:exc:`FunctionNotFound`.

        >>> def foo(): pass
        >>> algo = Algorithm(foo)
        >>> def bar(): pass
        >>> algo.insert_after('foo', bar)
        >>> algo.get_names()
        ['foo', 'bar']
        >>> def baz(): pass
        >>> algo.insert_after('bar', baz)
        >>> algo.get_names()
        ['foo', 'bar', 'baz']
        >>> def bal(): pass
        >>> algo.insert_after(Algorithm.START, bal)
        >>> algo.get_names()
        ['bal', 'foo', 'bar', 'baz']
        >>> def bah(): pass
        >>> algo.insert_before(Algorithm.END, bah)
        >>> algo.get_names()
        ['bal', 'foo', 'bar', 'baz', 'bah']

        """
        if name == self.START:
            i = 0
        elif name == self.END:
            i = len(self.functions)
        else:
            i = self.functions.index(self[name]) + 1
        self.functions[i:i] = newfuncs


    def remove(self, *names):
        """Remove the functions named ``name`` from the :py:attr:`functions` list, or raise
        :py:exc:`FunctionNotFound`.
        """
        for name in names:
            func = self[name]
            self.functions.remove(func)


    @classmethod
    def from_dotted_name(cls, dotted_name, **kw):
        """Construct a new instance from functions defined in a Python module.

        :param dotted_name: the dotted name of a Python module that contains
            functions that will be added to algorithm in the order of appearance.

        :param kw: keyword arguments are passed through to the default constructor

        This is a convenience constructor to instantiate an algorithm based on
        functions defined in a regular Python file. For example, create a file named
        ``blah_algorithm.py`` on your ``PYTHONPATH``::

            def foo():
                return {'baz': 1}

            def bar():
                return {'buz': 2}

            def bloo(baz, buz):
                return {'sum': baz + buz}


        Then pass the dotted name of the file to this constructor:

        >>> blah = Algorithm.from_dotted_name('blah_algorithm')

        All functions defined in the file whose name doesn't begin with ``_``
        are loaded into a list in the order they're defined in the file, and
        this list is passed to the default class constructor.

        >>> blah.functions #doctest: +ELLIPSIS
        [<function foo ...>, <function bar ...>, <function bloo ...>]
        
        For this specific module, the code above is equivalent to:
        
        >>> from blah_algorithm import foo, bar, bloo
        >>> Algorithm(foo, bar, bloo)

        """
        module = cls._load_module_from_dotted_name(dotted_name)
        functions = cls._load_functions_from_module(module)
        return cls(*functions, **kw)


    def debug(self, function):
        """Given a function, return a copy of the function with a breakpoint
        immediately inside it.

        :param function function: a function object

        This method wraps the module-level function :py:func:`algorithm.debug`,
        adding three conveniences.

        First, calling this method not only returns a copy of the function with
        a breakpoint installed, it actually replaces the old function in the
        algorithm with the copy. So you can do:

        >>> def foo():
        ...     pass
        ...
        >>> algo = Algorithm(foo)
        >>> algo.debug(foo)             #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Second, it provides a method on itself to install via function name
        instead of function object:

        >>> algo = Algorithm(foo)
        >>> algo.debug.by_name('foo')   #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Third, it aliases the :py:meth:`~DebugMethod.by_name` method as
        :py:meth:`~_DebugMethod.__getitem__` so you can use mapping access as well:

        >>> algo = Algorithm(foo)
        >>> algo.debug['foo']           #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Why would you want to do that? Well, let's say you've written a library
        that includes an algorithm:

        >>> def foo(): pass
        ...
        >>> def bar(): pass
        ...
        >>> def baz(): pass
        ...
        >>> blah = Algorithm(foo, bar, baz)

        And now some user of your library ends up rebuilding the functions list
        using some of the original functions and some of their own:

        >>> def mine(): pass
        ...
        >>> def precious(): pass
        ...
        >>> blah.functions = [ blah['foo']
        ...                  , mine
        ...                  , blah['bar']
        ...                  , precious
        ...                  , blah['baz']
        ...                   ]

        Now the user of your library wants to debug ``blah['bar']``, but since
        they're using your code as a library it's inconvenient for them to drop
        a breakpoint in your source code. With this feature, they can just
        insert ``.debug`` in their own source code like so:

        >>> blah.functions = [ blah['foo']
        ...                  , mine
        ...                  , blah.debug['bar']
        ...                  , precious
        ...                  , blah['baz']
        ...                   ]

        Now when they run the algorithm they'll hit a pdb breakpoint just
        inside your ``bar`` function:

        >>> blah.run()              #doctest: +SKIP
        (Pdb)

        """
        raise NotImplementedError  # Should be overriden by _DebugMethod in constructor.


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
            lineno = func.__code__.co_firstlineno
            functions_with_lineno.append((lineno, func))
        functions_with_lineno.sort()
        return [func for lineno, func in functions_with_lineno]


# Debugging Helpers
# =================

class _DebugMethod(object):
    # See docstring at Algorithm.debug.

    def __init__(self, algorithm):
        self.algorithm = algorithm

    def __call__(self, function):
        debugging_function = debug(function)
        for i, candidate in enumerate(self.algorithm.functions):
            if candidate is function:
                self.algorithm.functions[i] = debugging_function
        return debugging_function

    def by_name(self, name):
        return self(self.algorithm[name])

    __getitem__ = by_name


def debug(function):
    """Given a function, return a copy of the function with a breakpoint
    immediately inside it.

    :param function function: a function object

    Okay! This is fun. :-)

    This is a decorator, because it takes a function and returns a function.
    But it would be useless in situations where you could actually decorate a
    function using the normal decorator syntax, because then you have the
    source code in front of you and you could just insert the breakpoint
    yourself. It's also pretty useless when you have a function object that
    you're about to call, because you can simply add a ``set_trace`` before the
    function call and then step into the function. No: this helper is only
    useful when you've got a function object that you want to debug, and you
    have neither the definition nor the call conveniently at hand. See the
    method :py:meth:`Algorithm.debug` for an explanation of how this situation
    arises with the :py:mod:`algorithm` module.

    For our purposes here, it's enough to know that you can wrap any function:

    >>> def foo(bar, baz):
    ...     return bar + baz
    ...
    >>> func = debug(foo)

    And then calling the function will drop you into pdb:

    >>> func(1, 2)                  #doctest: +SKIP
    (Pdb)

    The fun part is how this is implemented: we dynamically modify the
    function's bytecode to insert the statements ``import pdb;
    pdb.set_trace()``.  Neat, huh? :-)

    """

    # Build bytecode for a set_trace call.
    # ====================================

    NOARG = object()

    codes = ( ('LOAD_CONST', 0)
            , ('LOAD_CONST', None)
            , ('IMPORT_NAME', 'pdb')
            , ('STORE_GLOBAL', 'pdb')
            , ('LOAD_GLOBAL', 'pdb')
            , ('LOAD_ATTR', 'set_trace')
            , ('CALL_FUNCTION', 0)
            , ('POP_TOP', NOARG)
             )

    new_names = function.__code__.co_names
    new_consts = function.__code__.co_consts
    new_code = b''
    addr_pad = 0

    if PYTHON_2:
        _chr = chr
    else:

        # In Python 3 chr returns a str (== 2's unicode), not a bytes (== 2's
        # str). However, the func_new constructor wants a bytes for both code
        # and lnotab. We use latin-1 to encode these to bytes, per the docs:
        #
        #   The simplest method is to map the codepoints 0-255 to the bytes
        #   0x0-0xff. This means that a string object that contains codepoints
        #   above U+00FF can't be encoded with this method (which is called
        #   'latin-1' or 'iso-8859-1').
        #
        #   http://docs.python.org/3/library/codecs.html#encodings-and-unicode

        _chr = lambda x: chr(x).encode('latin-1')

    for name, arg in codes:

        # This is the inverse of the subset of dis.disassemble needed to handle
        # our use case.

        addr_pad += 1
        op = opcode.opmap[name]
        new_code += _chr(op)
        if op >= opcode.HAVE_ARGUMENT:
            addr_pad += 2
            if op in opcode.hasconst:
                if arg not in new_consts:
                    new_consts += (arg,)
                val = new_consts.index(arg)
            elif op in opcode.hasname:
                if PYTHON_2:
                    # In Python 3, func_new wants str (== unicode) for names.
                    arg = arg.encode('ASCII')
                if arg not in new_names:
                    new_names += (arg,)
                val = new_names.index(arg)
            elif name == 'CALL_FUNCTION':
                val = arg  # number of args
            new_code += _chr(val) + _chr(0)


    # Finish inserting our new bytecode in front of the old.
    # ======================================================
    # Loop over old_code and append it to new_code, fixing up absolute jump
    # references along the way. Then fix up the line number table.

    old_code = function.__code__.co_code
    i = 0
    n = len(old_code)
    while i < n:
        c = old_code[i]
        if type(c) is int:
            # In Python 3, index access on a bytestring returns an int.
            c = _chr(c)
        op = ord(c)
        i += 1
        new_code += c
        if op >= opcode.HAVE_ARGUMENT:
            if PYTHON_2:
                oparg = ord(old_code[i]) + ord(old_code[i+1])*256
            else:
                oparg = old_code[i] + old_code[i+1]*256
            if op in opcode.hasjabs:
                oparg += addr_pad
            i += 2
            new_code += _chr(oparg) + _chr(0)

    old = function.__code__.co_lnotab
    new_lnotab = ( old[:2]
                 + _chr( (ord(old[2]) if len(old) > 2 else 0)
                       + addr_pad
                        )
                 + old[3:]
                  )


    # Now construct new code and function objects.
    # ============================================
    # See Objects/codeobject.c in Python source.

    common_args = ( function.__code__.co_nlocals
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

    if PYTHON_2:
        new_code = type(function.__code__)(function.__code__.co_argcount, *common_args)
        new_function = type(function)( new_code
                                     , function.func_globals
                                     , function.func_name
                                     , function.func_defaults
                                     , function.func_closure
                                      )
    else:
        new_code = type(function.__code__)( function.__code__.co_argcount
                                          , function.__code__.co_kwonlyargcount
                                          , *common_args
                                           )
        new_function = type(function)( new_code
                                     , function.__globals__
                                     , function.__name__
                                     , function.__defaults__
                                     , function.__closure__
                                      )

    return new_function


if __name__ == '__main__':
    import doctest
    doctest.testmod()
