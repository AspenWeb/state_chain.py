"""Model a process lifecycle as a list of functions.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import sys
import types
import traceback


class FunctionNotFound(Exception):
    def __str__(self):
        return "The function '{0}' isn't in this lifecycle.".format(*self.args)


class Lifecycle(object):

    short_circuit = False

    def __init__(self, dotted_name):
        self.module = self._load_module_from_dotted_name(dotted_name)
        self.functions = self._load_functions_from_module(self.module)


    def __iter__(self):
        return iter(self.functions)


    def get_names(self):
        return [f.func_name for f in self]


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
            if func.func_name == name:
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
            function_name = function.func_name
            try:
                deps = self._resolve_dependencies(function, state)
                if 'exc_info' in deps.required and state['exc_info'] is None:
                    pass    # Hook needs an exc_info but we don't have it.
                    #print("{0:>48}  \x1b[33;1mskipped\x1b[0m".format(function_name))
                elif 'exc_info' not in deps.names and state['exc_info'] is not None:
                    pass    # Hook doesn't want an exc_info but we have it.
                    #print("{0:>48}  \x1b[33;1mskipped\x1b[0m".format(function_name))
                else:
                    new_state = function(**deps.kw)
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
        exec 'import {0}'.format(dotted_name) in module.__dict__
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
            lineno = func.func_code.co_firstlineno
            functions_with_lineno.append((lineno, func))
        functions_with_lineno.sort()
        return [func for lineno, func in functions_with_lineno]
