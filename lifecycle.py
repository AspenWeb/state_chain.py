"""Model a process lifecycle as a list of functions.

Installation
------------

:py:mod:`lifecycle` is available on `GitHub`_ and on `PyPI`_::

    $ pip install lifecycle

We `test <https://travis-ci.org/gittip/lifecycle.py>`_ against
Python 2.6, 2.7, 3.2, and 3.3.

:py:mod:`lifecycle` is in the `public domain`_.


.. _GitHub: https://github.com/gittip/lifecycle.py
.. _PyPI: https://pypi.python.org/pypi/lifecycle
.. _public domain: http://creativecommons.org/publicdomain/zero/1.0/


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
        return "The function '{0}' isn't in this lifecycle.".format(*self.args)


class Lifecycle(object):
    """Represent a process lifecycle.
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
        self.insert_relative_to(name, newfunc, relative_position=-1)


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


    def run(self, state, through=None):
        """Given a state dictionary, run through the functions in the list.
        """
        if through is not None:
            if through not in self.get_names():
                raise FunctionNotFound(through)
        # XXX bring these back when we've sorted out logging
        #print()

        if 'lifecycle' not in state:    state['lifecycle'] = self
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

            if through is not None and function_name == through:
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
