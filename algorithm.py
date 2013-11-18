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
    >>> blah = Algorithm('blah_algorithm')


When you instantiate :py:class:`Algorithm` you give it the dotted path to a
Python module. All of the functions defined in the module are loaded into a
list, in the order they're defined in the file:

    >>> blah.functions #doctest: +ELLIPSIS
    [<function foo ...>, <function bar ...>, <function bloo ...>]


Now you can use :py:func:`~Algorithm.run` to run the algorithm. You'll get back
a dictionary representing the algorithm's final state:

    >>> state = blah.run()
    >>> state['sum']
    3


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

import re
import sys
import types
import traceback

from dependency_injection import resolve_dependencies


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


class FunctionNotFound(Exception):
    def __str__(self):
        return "The function '{0}' isn't in this algorithm.".format(*self.args)


class Algorithm(object):
    """Model an algorithm as a list of functions.

    :param dotted_name: The dotted name of a Python module containing the
        algorithm definition.


    Each function in your algorithm must return a mapping or :py:class:`None`.
    If it returns a mapping, that will be used to update the state of the
    current run of the algorithm. Functions in the algorithm can use any name
    from the current state as a parameter, and the values will then be supplied
    via :py:mod:`dependency_injection`.

    """

    short_circuit = False

    def __init__(self, dotted_name):
        self.module = self._load_module_from_dotted_name(dotted_name)
        self.functions = self._load_functions_from_module(self.module)


    def __iter__(self):
        return iter(self.functions)


    def get_names(self):
        return [_get_func_name(f) for f in self]


    def insert_after(self, name, newfunc):
        """Insert newfunc in the list right after the function named name.
        """
        self.insert_relative_to(name, newfunc, relative_position=1)


    def insert_before(self, name, newfunc):
        """Insert newfunc in the list right before the function named name.
        """
        self.insert_relative_to(name, newfunc, relative_position=0)


    def insert_relative_to(self, name, newfunc, relative_position):
        func = self.resolve_name_to_function(name)
        index = self.functions.index(func) + relative_position
        self.functions.insert(index, newfunc)


    def remove(self, name):
        """Remove the function named name from the list.
        """
        func = self.resolve_name_to_function(name)
        self.functions.remove(func)


    def resolve_name_to_function(self, name):
        """Given the name of a function in the list, return the function itself.
        """
        func = None
        for func in self.functions:
            if _get_func_name(func) == name:
                break
        if func is None:
            raise FunctionNotFound(name)
        return func


    def run(self, _through=None, **state):
        """Given a state dictionary, run through the functions in the list.
        """
        if _through is not None:
            if _through not in self.get_names():
                raise FunctionNotFound(_through)
        # XXX bring these back when we've sorted out logging
        #print()

        if 'algorithm' not in state:    state['algorithm'] = self
        if 'state' not in state:        state['state'] = state
        if 'exc_info' not in state:     state['exc_info'] = None

        for function in self.functions:
            function_name = _get_func_name(function)
            try:
                deps = resolve_dependencies(function, state)
                if 'exc_info' in deps.signature.required and state['exc_info'] is None:
                    pass    # Hook needs an exc_info but we don't have it.
                    #print("{0:>48}  \x1b[33;1mskipped\x1b[0m".format(function_name))
                elif 'exc_info' not in deps.signature.parameters and state['exc_info'] is not None:
                    pass    # Hook doesn't want an exc_info but we have it.
                    #print("{0:>48}  \x1b[33;1mskipped\x1b[0m".format(function_name))
                else:
                    new_state = function(**deps.as_kwargs)
                    #print("{0:>48}  \x1b[32;1mdone\x1b[0m".format(function_name))
                    if new_state is not None:
                        state.update(new_state)
            except:
                #print("{0:>48}  \x1b[31;1mfailed\x1b[0m".format(function_name))
                state['exc_info'] = sys.exc_info()[:2] + (traceback.format_exc().strip(),)
                if self.short_circuit:
                    raise

            if _through is not None and function_name == _through:
                break

        if state['exc_info'] is not None:
            raise

        return state


    # Helpers for loading from a file.
    # ================================

    def _load_module_from_dotted_name(self, dotted_name):
        class Module(object): pass
        module = Module()  # let's us use getattr to traverse down
        exec_('import {0}'.format(dotted_name), module.__dict__)
        for name in dotted_name.split('.'):
            module = getattr(module, name)
        return module


    def _load_functions_from_module(self, module):
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


# Filters
# =======

def by_lambda(filter_lambda):
    def wrap(flow_step):
        def wrapped_flow_step_by_lambda(*args,**kwargs):
            if filter_lambda():
                return flow_step(*args,**kwargs)
        _transfer_func_name(wrapped_flow_step_by_lambda, flow_step)
        return wrapped_flow_step_by_lambda
    return wrap


def by_regex(regex_tuples, default=True):
    """A filter for flow steps.

    regex_tuples is a list of (regex, filter?) where if the regex matches the
    requested URI, then the flow is applied or not based on if filter? is True
    or False.

    For example:

        from aspen.flows.filter import by_regex

        @by_regex( ( ("/secret/agenda", True), ( "/secret.*", False ) ) )
        def use_public_formatting(request):
            ...

    would call the 'use_public_formatting' flow step only on /secret/agenda
    and any other URLs not starting with /secret.

    """
    regex_res = [ (re.compile(regex), disposition) \
                           for regex, disposition in regex_tuples.iteritems() ]
    def filter_flow_step(flow_step):
        def flow_step_filter(request, *args):
            for regex, disposition in regex_res:
                if regex.matches(request.line.uri):
                    if disposition:
                        return flow_step(*args)
            if default:
                return flow_step(*args)
        _transfer_func_name(flow_step_filter, flow_step)
        return flow_step_filter
    return filter_flow_step


def by_dict(truthdict, default=True):
    """A filter for hooks.

    truthdict is a mapping of URI -> filter? where if the requested URI is a
    key in the dict, then the hook is applied based on the filter? value.

    """
    def filter_flow_step(flow_step):
        def flow_step_filter(request, *args):
            do_hook = truthdict.get(request.line.uri, default)
            if do_hook:
                return flow_step(*args)
        flow_step_filter.func_name = flow_step.func_name
        return flow_step_filter
    return filter_flow_step


if __name__ == '__main__':
    import doctest
    doctest.testmod()
