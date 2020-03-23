"""Model algorithms as a list of functions operating on a shared state dict.


Installation
------------

:py:mod:`state_chain` is available on `GitHub`_ and on `PyPI`_::

    $ pip install state_chain

The version of :py:mod:`state_chain` documented here has been `tested`_ against
Python 3.6, 3.7 and 3.8 on Ubuntu.

:py:mod:`state_chain` is MIT-licensed.


.. _GitHub: https://github.com/AspenWeb/state_chain.py
.. _PyPI: https://pypi.python.org/pypi/state_chain
.. _tested: https://travis-ci.org/AspenWeb/state_chain.py


Tutorial
--------

This module provides an abstraction for implementing arbitrary algorithms as a
list of functions that operate on a shared state dictionary. Algorithms defined
this way are easy to arbitrarily modify at run time, and they provide cascading
exception handling.

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


Each function returns a :py:class:`dict`, which is used to update the state of
the current run of the algorithm. Names from the state dictionary are made
available to downstream functions via :py:mod:`dependency_injection`. Now
make an :py:class:`StateChain` object:

    >>> from state_chain import StateChain
    >>> blah = StateChain(foo, bar, bloo)


The functions you passed to the constructor are loaded into a list:

    >>> blah.functions          #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function bloo ...>]


Now you can use :py:func:`~StateChain.run` to run the functions. You'll get back
a dictionary representing the algorithm's final state:

    >>> state = blah.run()
    >>> state['sum']
    3

Okay!


Modifying a State Chain
+++++++++++++++++++++++

Let's add two functions to the state chain. First let's define the functions:

    >>> def uh_oh(baz):
    ...     if baz == 2:
    ...         raise heck
    ...
    >>> def deal_with_it(exception):
    ...     print("I am dealing with it!")
    ...     return {'exception': None}
    ...


Now let's interpolate them into our state chain. Let's put the ``uh_oh``
function between ``bar`` and ``bloo``:

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


If you're making extensive changes to a state chain, you should feel free to
directly manipulate the list of functions, rather than using the more
cumbersome :py:meth:`~state_chain.StateChain.insert_before`,
:py:meth:`~state_chain.StateChain.insert_after`, and
:py:meth:`~state_chain.StateChain.remove` methods. We could have achieved the
same result like so:

    >>> blah.functions = [ blah['bar']
    ...                  , uh_oh
    ...                  , blah['bloo']
    ...                  , deal_with_it
    ...                   ]
    >>> blah.functions      #doctest: +ELLIPSIS
    [<function bar ...>, <function uh_oh ...>, <function bloo ...>, <function deal_with_it ...>]


Either way, what happens when we run it? Since we no longer have the ``foo``
function providing a value for ``bar``, we'll need to supply that using a
keyword argument to :py:func:`~StateChain.run`:

    >>> state = blah.run(baz=2)
    I am dealing with it!


Exception Handling
++++++++++++++++++

Whenever a function raises an exception, like ``uh_oh`` did in the example
above, :py:class:`~StateChain.run` captures the exception and populates an
``exception`` key in the current run's state dictionary. While ``exception`` is
not ``None``, any normal function is skipped, and only functions that ask for
``exception`` get called. It's like a fast-forward. So in our example
``deal_with_it`` got called, but ``bloo`` didn't, which is why there is no
``sum``:

    >>> 'sum' in state
    False


If we run without tripping the exception in ``uh_oh`` then we have ``sum`` at
the end:

    >>> blah.run(baz=5)['sum']
    7


API Reference
-------------

"""

import opcode
import sys
import types

from dependency_injection import get_signature, resolve_dependencies


__version__ = '1.4.0'


class FunctionNotFound(KeyError):
    """Used when a function is not found in a state_chain function list
    (subclasses :py:exc:`KeyError`).
    """
    def __str__(self):
        return "The function '{0}' isn't in this state chain.".format(*self.args)


_NO_PREVIOUS = object()

def _iter_with_previous(iterable):
    prev = _NO_PREVIOUS
    for o in iterable:
        yield o, prev
        prev = o


class StateChain:
    """Model an algorithm as a list of functions operating on a shared state
    dictionary.

    :param functions: a sequence of functions in the order they are to be run
    :param bool raise_immediately: Whether to re-raise exceptions immediately.
        :py:class:`False` by default, this can only be set as a keyword argument

    Each function in the state chain must return a mapping or :py:class:`None`.
    If it returns a mapping, the mapping will be used to update a state
    dictionary for the current run of the algorithm. Functions in the state
    chain can use any name from the current state dictionary as a parameter,
    and the value will then be supplied dynamically via
    :py:mod:`dependency_injection`.  See the :py:func:`run` method for details
    on exception handling.

    """

    START = -1
    END = -2

    def __init__(self, *functions, **kw):
        self.default_raise_immediately = kw.pop('raise_immediately', False)
        for f in functions:
            if not callable(f):
                raise TypeError("Not a function: {0}".format(repr(f)))
        self.functions = list(functions)
        self._signatures = {}
        self.debug = _DebugMethod(self)


    def run(self, state=None, _raise_immediately=None, _return_after=None, **kw):
        """Run through the functions in the :py:attr:`functions` list.

        :param dict state: the initial state dictionary for this run of the chain

        :param bool _raise_immediately: if not ``None``, will override any
            default for ``raise_immediately`` that was set in the constructor

        :param str _return_after: if not ``None``, return after calling the function
            with this name

        :param kw: remaining keyword arguments are added to the ``state`` dict

        :raises: :py:exc:`FunctionNotFound`, if there is no function named
            ``_return_after``

        :returns: a dictionary representing the final state

        The state dictionary is initialized with three items (their default
        values can be overriden using keyword arguments to :py:func:`run`):

         - ``chain`` - a reference to the parent :py:class:`StateChain` instance
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
           handling.

         - If an exception is raised by a function handling another exception,
           then ``exception`` is set to the new one and we look for the next
           exception handler.

         - If ``exception`` is not ``None`` after all functions have been run,
           then we re-raise it.

         - If ``raise_immediately`` evaluates to ``True`` (looking first at any
           per-call ``_raise_immediately`` and then at the instance default),
           then we re-raise any exception immediately instead of
           fast-forwarding to the next exception handler.

         - When an exception occurs, the functions that accept an ``exception``
           argument will be called from inside the ``except:`` block, so you
           can access ``sys.exc_info`` (which contains the traceback).

        """

        if state is None:
            state = {}
        if kw:
            state.update(kw)

        if _raise_immediately is None:
            _raise_immediately = self.default_raise_immediately

        if _return_after is not None:
            if _return_after not in self.get_names():
                raise FunctionNotFound(_return_after)

        if 'chain' not in state:        state['chain'] = self
        if 'state' not in state:        state['state'] = state
        if 'exception' not in state:    state['exception'] = None

        # The `for` loop in the `loop()` function below can be entered multiple
        # times since that function calls itself when an exception is raised.
        # If we looped over the `functions` list we'd be starting from the top
        # at each exception, and that's not what we want, so we use an iterator
        # instead to keep track of where we are in the state chain.
        functions_iter = _iter_with_previous(self.functions)

        def loop(in_except):
            signatures = self._signatures
            for function, prev_func in functions_iter:
                if _return_after is not None and prev_func is not _NO_PREVIOUS:
                    if prev_func.__name__ == _return_after:
                        break
                try:
                    if function not in signatures:
                        signatures[function] = get_signature(function)
                    deps = resolve_dependencies(signatures[function], state)
                    skip = (
                        # When function wants exception but we don't have it.
                        not in_except and 'exception' in deps.signature.required
                        or
                        # When function doesn't want exception but we have it.
                        in_except and 'exception' not in deps.signature.parameters
                    )
                    if not skip:
                        new_state = function(**deps.as_kwargs)
                        if new_state is not None:
                            state.update(new_state)
                        if in_except and state['exception'] is None:
                            # exception is cleared, return to normal flow
                            return
                except Exception:
                    if _raise_immediately:
                        raise
                    state['exception'] = sys.exc_info()[1]
                    loop(True)
                    if in_except:
                        # an exception occurred while we were handling another
                        # exception, but now it's been cleared, so we return to
                        # the normal flow
                        return
            if in_except:
                raise  # exception hasn't been handled, reraise

        loop(False)

        return state

    def __getitem__(self, name):
        """Return the function in the :py:attr:`functions` list named ``name``, or raise
        :py:exc:`FunctionNotFound`.

        >>> def foo(): pass
        >>> algo = StateChain(foo)
        >>> algo['foo'] is foo
        True
        >>> algo['bar']
        Traceback (most recent call last):
          ...
        state_chain.FunctionNotFound: The function 'bar' isn't in this state chain.

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
        >>> algo = StateChain(foo)
        >>> def bar(): pass
        >>> algo.insert_before('foo', bar)
        >>> algo.get_names()
        ['bar', 'foo']
        >>> def baz(): pass
        >>> algo.insert_before('foo', baz)
        >>> algo.get_names()
        ['bar', 'baz', 'foo']
        >>> def bal(): pass
        >>> algo.insert_before(StateChain.START, bal)
        >>> algo.get_names()
        ['bal', 'bar', 'baz', 'foo']
        >>> def bah(): pass
        >>> algo.insert_before(StateChain.END, bah)
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
        >>> algo = StateChain(foo)
        >>> def bar(): pass
        >>> algo.insert_after('foo', bar)
        >>> algo.get_names()
        ['foo', 'bar']
        >>> def baz(): pass
        >>> algo.insert_after('bar', baz)
        >>> algo.get_names()
        ['foo', 'bar', 'baz']
        >>> def bal(): pass
        >>> algo.insert_after(StateChain.START, bal)
        >>> algo.get_names()
        ['bal', 'foo', 'bar', 'baz']
        >>> def bah(): pass
        >>> algo.insert_before(StateChain.END, bah)
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
            functions that will be added to a state chain in the order of appearance.

        :param kw: keyword arguments are passed through to the default constructor

        This is a convenience constructor to instantiate a state chain based on
        functions defined in a regular Python file. For example, create a file named
        ``blah_state_chain.py`` on your ``PYTHONPATH``::

            def foo():
                return {'baz': 1}

            def bar():
                return {'buz': 2}

            def bloo(baz, buz):
                return {'sum': baz + buz}


        Then pass the dotted name of the file to this constructor:

        >>> blah = StateChain.from_dotted_name('blah_state_chain')

        All functions defined in the file whose name doesn't begin with ``_``
        are loaded into a list in the order they're defined in the file, and
        this list is passed to the default class constructor.

        >>> blah.functions #doctest: +ELLIPSIS
        [<function foo ...>, <function bar ...>, <function bloo ...>]

        For this specific module, the code above is equivalent to:

        >>> from blah_state_chain import foo, bar, bloo
        >>> blah = StateChain(foo, bar, bloo)

        """
        module = cls._load_module_from_dotted_name(dotted_name)
        functions = cls._load_functions_from_module(module)
        return cls(*functions, **kw)

    def debug(self, function):
        """Given a function, return a copy of the function with a breakpoint
        immediately inside it.

        :param function function: a function object

        This method wraps the module-level function
        :py:func:`state_chain.debug`, adding three conveniences.

        First, calling this method not only returns a copy of the function with
        a breakpoint installed, it actually replaces the old function in the
        state chain with the copy. So you can do:

        >>> def foo():
        ...     pass
        ...
        >>> algo = StateChain(foo)
        >>> algo.debug(foo)             #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Second, it provides a method on itself to install via function name
        instead of function object:

        >>> algo = StateChain(foo)
        >>> algo.debug.by_name('foo')   #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Third, it aliases the :py:meth:`~DebugMethod.by_name` method as
        :py:meth:`~_DebugMethod.__getitem__` so you can use mapping access as well:

        >>> algo = StateChain(foo)
        >>> algo.debug['foo']           #doctest: +ELLIPSIS
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Why would you want to do that? Well, let's say you've written a library
        that includes a state chain:

        >>> def foo(): pass
        ...
        >>> def bar(): pass
        ...
        >>> def baz(): pass
        ...
        >>> blah = StateChain(foo, bar, baz)

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

        Now when they run the state chain they'll hit a pdb breakpoint just
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
        exec('import {0}'.format(dotted_name), module.__dict__)
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
        return [f for i, f in functions_with_lineno]


# Debugging Helpers
# =================

class _DebugMethod(object):
    # See docstring at StateChain.debug.

    def __init__(self, chain):
        self.chain = chain

    def __call__(self, function):
        debugging_function = debug(function)
        for i, candidate in enumerate(self.chain.functions):
            if candidate is function:
                self.chain.functions[i] = debugging_function
        return debugging_function

    def by_name(self, name):
        return self(self.chain[name])

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
    method :py:meth:`StateChain.debug` for an explanation of how this situation
    arises with the :py:mod:`state_chain` module.

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

    codes = ( ('LOAD_CONST', 0)
            , ('LOAD_CONST', None)
            , ('IMPORT_NAME', 'pdb')
            , ('STORE_GLOBAL', 'pdb')
            , ('LOAD_GLOBAL', 'pdb')
            , ('LOAD_ATTR', 'set_trace')
            , ('CALL_FUNCTION', 0)
            , ('POP_TOP', 0)
             )

    new_names = function.__code__.co_names
    new_consts = function.__code__.co_consts
    new_code = b''
    addr_pad = 0

    for name, arg in codes:
        # Since Python 3.6, all instructions use exactly two bytes.
        addr_pad += 2
        op = opcode.opmap[name]
        if op in opcode.hasconst:
            if arg not in new_consts:
                new_consts += (arg,)
            arg = new_consts.index(arg)
        elif op in opcode.hasname:
            if arg not in new_names:
                new_names += (arg,)
            arg = new_names.index(arg)
        if arg > 0xffffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 24) & 0xff))
        if arg > 0xffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 16) & 0xff))
        if arg > 0xff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 8) & 0xff))
            arg &= 0xff
        new_code += bytes((op, arg))

    # Insert our new bytecode in front of the old.
    # ============================================
    # Loop over old_code and append it to new_code, fixing up absolute jump
    # references along the way. Adapted from `dis._unpack_opargs()`.

    old_code = function.__code__.co_code
    i = 0
    extended_arg = 0
    for i in range(0, len(old_code), 2):
        # In Python 3, index access on a bytestring returns an int.
        op = old_code[i]
        arg = old_code[i+1] | extended_arg
        if op == opcode.EXTENDED_ARG:
            extended_arg = arg << 8
            continue
        else:
            extended_arg = 0
        if op in opcode.hasjabs:
            arg += addr_pad
        if arg > 0xffffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 24) & 0xff))
        if arg > 0xffff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 16) & 0xff))
        if arg > 0xff:
            new_code += bytes((opcode.EXTENDED_ARG, (arg >> 8) & 0xff))
            arg &= 0xff
        new_code += bytes((op, arg))

    # Fix up the line number table.
    # =============================
    # See https://github.com/python/cpython/blob/3.8/Objects/lnotab_notes.txt

    old = function.__code__.co_lnotab
    new_lnotab = bytes((addr_pad, 0)) + old

    # Now construct new code and function objects.
    # ============================================
    # See Objects/codeobject.c in Python source.

    if hasattr(function.__code__, 'replace'):
        # Python >= 3.8
        new_code = function.__code__.replace(
            co_code=new_code,
            co_consts=new_consts,
            co_names=new_names,
            co_lnotab=new_lnotab,
        )
    else:
        new_code = type(function.__code__)(
            function.__code__.co_argcount,
            function.__code__.co_kwonlyargcount,
            function.__code__.co_nlocals,
            function.__code__.co_stacksize,
            function.__code__.co_flags,
            new_code,
            new_consts,
            new_names,
            function.__code__.co_varnames,
            function.__code__.co_filename,
            function.__code__.co_name,
            function.__code__.co_firstlineno,
            new_lnotab,
            function.__code__.co_freevars,
            function.__code__.co_cellvars,
        )
    new_function = type(function)(
        new_code,
        function.__globals__,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )

    return new_function
