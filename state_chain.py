from collections import OrderedDict
from functools import partial
from inspect import Parameter, Signature, signature
import opcode
import sys
from types import CodeType, FunctionType, SimpleNamespace
from typing import (
    cast, Any, Callable, Dict, Generic, Iterable, List, NamedTuple, NoReturn,
    Optional, Tuple, TYPE_CHECKING, Type, TypeVar, Union
)


__version__ = '2.0rc1'


if TYPE_CHECKING:
    from typing_extensions import Literal, Protocol

    ExceptionPref = Literal['unwanted', 'accepted', 'required']

    class StateProtocol(Protocol):
        """Typing protocol for the state objects of chains.
        """
        exception: Optional[Exception]

else:
    ExceptionPref = str
    StateProtocol = None

State = TypeVar('State', bound=StateProtocol)
ChainFunction = Callable
ChainFunctionRef = Union[ChainFunction, str]
Func = TypeVar('Func', bound=Callable)
T = TypeVar('T')


class _LoopState:
    __slots__ = ('i', 'prev_func')

    def __init__(self) -> None:
        self.i: int = 0
        self.prev_func: Optional[ChainFunction] = None


class _ChainLink(NamedTuple):
    function: ChainFunction
    exception_pref: ExceptionPref
    signature: Optional[Signature]


class _FunctionMapValue:

    __slots__ = ('function', 'position')

    def __init__(self, function: ChainFunction, position: Optional[int]):
        self.function = function
        self.position = position

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.function!r}, {self.position!r})"


class Object(SimpleNamespace):
    """The default type of a chain's :obj:`state` object.

    A namespace that supports both attribute-style and dict-style lookups and
    assignments. This is similar to a JavaScript object, hence the name.
    """

    def __init__(
        self,
        *d: Union[Dict[str, Any], Iterable[Tuple[str, Any]]],
        **kw: Dict[str, Any],
    ) -> None:
        self.__dict__.update(*d, **kw)

    def __contains__(self, key: str) -> bool:
        return key in self.__dict__

    def __getitem__(self, key: str) -> Any:
        return self.__dict__[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.__dict__[key] = value


class StateChain(Generic[State]):
    """Model an algorithm as a list of functions operating on a shared state.

    :param type state_type: the type of the state object
    :param functions: a sequence of functions in the order they are to be run
    :param bool raise_immediately: default value for the `raise_immediately`
        argument of the :meth:`run` method
    :param str exception_preference: default value for the `exception` argument
        of the :meth:`add` method

    """

    __slots__ = (
        'state_type', 'raise_immediately', 'exception_preference', '_functions',
        '_functions_map', '__dict__',
    )

    def __init__(
        self,
        state_type: Type[State] = cast(Type[State], Object),
        functions: Iterable[ChainFunction] = (),
        raise_immediately: bool = False,
        exception_preference: ExceptionPref = 'unwanted',
    ):
        self.state_type = state_type
        self.exception_preference = exception_preference
        self._functions: Tuple[_ChainLink, ...] = ()
        self._functions_map: Dict[str, _FunctionMapValue] = {}
        self.add(*functions)
        self.raise_immediately = raise_immediately

    @property
    def functions(self) -> Tuple[ChainFunction, ...]:
        return tuple(link.function for link in self._functions)

    @functions.setter
    def functions(self, new_list: Any) -> NoReturn:
        raise AttributeError(
            "You should use the `modify()` method to customize a state chain. "
            "See https://state-chain-py.readthedocs.io/ for details."
        )

    def copy(self) -> 'StateChain':
        """Returns a copy of this chain.
        """
        r = StateChain(self.state_type, raise_immediately=self.raise_immediately)
        r._functions = self._functions
        r._functions_map = self._functions_map.copy()
        r.__dict__ = self.__dict__.copy()
        return r

    def run(
        self,
        state: Optional[State] = None,
        raise_immediately: Optional[bool] = None,
        return_after: Optional[str] = None,
    ) -> State:
        """Run through the functions in the :attr:`functions` list.

        :param State state: the initial state object for this run of the chain
            (`self.state_type()` is called to create an object if none is provided)

        :param bool raise_immediately: if not ``None``, will override any
            default for ``raise_immediately`` that was set in the constructor

        :param str return_after: if not ``None``, return after calling the function
            with this name

        :raises: :exc:`FunctionNotFound`, if there is no function named
            ``return_after``

        :returns: the ``state`` object

        For each function in the :attr:`functions` list, we look at the
        function's exception preference and at the current value of
        ``state.exception``. If ``state.exception`` is ``None``, then we skip
        any function whose exception preference is :obj:`'required'`, and if
        ``state.exception`` is *not* ``None`` then we only call functions whose
        exception preference is not :obj:`'unwanted'`. The upshot is that any
        function that raises an exception will cause us to fast-forward to the
        next exception-handling function in the list.

        Here are some further notes on exception handling:

         - If a function's exception preference is :attr:`'accepted'`, then that
           function will be called whether or not there is an exception being
           handled.

         - You should set ``state.exception = None`` when an exception has been
           handled. The chain run will resume normally from where it is (it
           won't backtrack to run the functions that were skipped during
           exception handling).

         - If an exception is raised by a function handling another exception,
           then ``state.exception`` is set to the new one and we look for the
           next exception handler.

         - If ``state.exception`` is not ``None`` after all functions have been
           run, then we re-raise it.

         - If ``raise_immediately`` evaluates to ``True`` (looking first at the
           ``raise_immediately`` argument and falling back to the chain's
           ``raise_immediately`` attribute), then we re-raise any exception
           immediately instead of fast-forwarding to the next exception handler.

         - When an exception occurs, the chain functions that handle it are
           called from inside the ``except:`` block, so you can access
           ``sys.exc_info`` (which contains the traceback).

        """

        if state is None:
            state = self.state_type()

        if raise_immediately is None:
            raise_immediately = self.raise_immediately

        return_after = self[return_after] if return_after else None

        if not hasattr(state, 'exception'):
            state.exception = None

        functions = self._functions
        j = len(functions)
        loop_state = _LoopState()

        def loop(
            # The first two arguments are for mypy's benefit.
            state: State,
            return_after: Optional[ChainFunction],
            in_except: bool
        ) -> None:
            while loop_state.i < j:
                function, exception_pref, sig = functions[loop_state.i]
                loop_state.i += 1
                if return_after:
                    if loop_state.prev_func is return_after:
                        break
                    loop_state.prev_func = function
                if in_except:
                    # Skip when function doesn't want exception but we have it.
                    if exception_pref == 'unwanted':
                        continue
                else:
                    # Skip when function wants exception but we don't have it.
                    if exception_pref == 'required':
                        continue
                try:
                    if sig:
                        call(function, state, sig)
                    else:
                        function(state)
                    if in_except and state.exception is None:
                        # exception is cleared, return to normal flow
                        return
                except Exception as e:
                    if raise_immediately:
                        raise
                    state.exception = e
                    loop(state, return_after, True)
                    if in_except:
                        # an exception occurred while we were handling another
                        # exception, but now it's been cleared, so we return to
                        # the normal flow
                        return
            if state.exception:
                raise state.exception  # exception hasn't been handled, reraise

        loop(state, return_after, state.exception is not None)

        return state

    def __contains__(self, func_ref: ChainFunctionRef) -> bool:
        if isinstance(func_ref, str):
            return func_ref in self._functions_map
        try:
            return self._functions_map[func_ref.__name__].function is func_ref
        except KeyError:
            return False

    def __getitem__(self, name: str) -> ChainFunction:
        """Return the function in the :attr:`functions` list named ``name``, or raise
        :exc:`FunctionNotFound`.

        >>> def foo(): pass
        >>> algo = StateChain(functions=[foo])
        >>> algo['foo'] is foo
        True
        >>> algo['bar']
        Traceback (most recent call last):
          ...
        state_chain.FunctionNotFound: The function 'bar' isn't in this state chain.

        """
        v = self._functions_map.get(name)
        if v is None:
            raise FunctionNotFound(name)
        return v.function

    def get_names(self) -> List[str]:
        """Returns a list of the names of the functions in the :attr:`functions` list.
        """
        return [f.__name__ for f in self.functions]

    def add(
        self,
        *funcs: ChainFunction,
        position: Optional[int] = None,
        exception: Optional[ExceptionPref] = None,
        alias: Optional[str] = None,
    ) -> Optional[ChainFunction]:
        """Insert functions into the chain.

        :param funcs: the function(s) to add to the chain
        :param int position: where to insert the function in the chain
        :param str exception: determines when this function will be run or skipped.
            The valid values are: 'unwanted', 'accepted', and 'required'.
        :param str alias: one or more alternative names for the function being added,
            separated by whitespace

        :raises: :exc:`TypeError` if an element of the ``funcs`` list isn't a callable,
            or if the ``alias`` argument is provided when adding multiple functions

        >>> from types import SimpleNamespace
        >>> algo = StateChain(SimpleNamespace)
        >>> @algo.add
        ... def foo(): pass

        >>> @algo.add(position=0)
        ... def bar(): pass
        >>> algo.get_names()
        ['bar', 'foo']

        >>> @algo.add(position=algo.after('bar'), exception='accepted')
        ... def baz(): pass
        >>> algo.get_names()
        ['bar', 'baz', 'foo']

        >>> @algo.add(position=algo.before('bar'), exception='required')
        ... def bal(): pass
        >>> algo.get_names()
        ['bal', 'bar', 'baz', 'foo']

        Of course, the method doesn't have to be used as a decorator:

        >>> def bah(): pass
        >>> algo.add(bah, position=0)
        <function bah at ...>
        >>> algo.get_names()
        ['bah', 'bal', 'bar', 'baz', 'foo']

        """
        if not funcs:
            return partial(self.add, position=position, exception=exception, alias=alias)
        for f in funcs:
            if not callable(f):
                raise TypeError("Not a function: " + repr(f))
        func_tuples = tuple(self._make_chain_link(f, exception) for f in funcs)
        if position is None:
            position = len(self._functions)
            self._functions += func_tuples
        else:
            after = self._functions[position:]
            self._functions = (
                self._functions[:position] + func_tuples + after
            )
            offset = len(funcs)
            for link in after:
                func_name = link.function.__name__
                v = self._functions_map[func_name]
                if v.position is not None:
                    v.position += offset
        if alias:
            if len(funcs) == 1:
                for a in alias.split():
                    self._functions_map[a] = _FunctionMapValue(funcs[0], position)
            else:
                raise TypeError(
                    "the `alias` argument is only allowed when adding a single "
                    "function to the chain"
                )
        for func in funcs:
            func_name = func.__name__
            if func_name in self._functions_map:
                self._functions_map[func_name].position = None
            else:
                self._functions_map[func_name] = _FunctionMapValue(func, position)
            position += 1
        if len(funcs) == 1:
            return funcs[0]
        else:
            return None  # for mypy

    def _make_chain_link(
        self,
        function: ChainFunction,
        exception: Optional[ExceptionPref],
    ) -> _ChainLink:
        sig = signature(function)
        if len(sig.parameters) == 1 and 'state' in sig.parameters:
            # This chain function takes the state object as its only argument,
            # so we don't need to keep its signature.
            return _ChainLink(function, exception or self.exception_preference, None)
        else:
            if not exception:
                exception_param = sig.parameters.get('exception')
                if exception_param is None:
                    exception = self.exception_preference
                elif exception_param.default is Parameter.empty:
                    exception = 'required'
                else:
                    exception = 'accepted'
            return _ChainLink(function, exception, sig)

    def after(self, func_name: str) -> int:
        """Returns the chain position immediately after the function named `func_name`.

        :raises: :exc:`FunctionHasMultiplePositions` if the matching function
            appears multiple times in this chain

        """
        v = self._functions_map.get(func_name)
        if v is None:
            raise FunctionNotFound(func_name)
        if v.position is None:
            raise FunctionHasMultiplePositions(func_name)
        return v.position + 1

    def before(self, func_name: str) -> int:
        """Returns the position of the function named `func_name` in this chain.

        :raises: :exc:`FunctionHasMultiplePositions` if the matching function
            appears multiple times in this chain

        """
        v = self._functions_map.get(func_name)
        if v is None:
            raise FunctionNotFound(func_name)
        if v.position is None:
            raise FunctionHasMultiplePositions(func_name)
        return v.position

    def remove(self, *names: str) -> None:
        """Remove the functions named ``name`` from the chain.

        :raises: :exc:`FunctionNotFound` if a name isn't found in the chain.

        """
        funcs = set(self[name] for name in names)
        self._functions = tuple(
            link for link in self._functions if link.function not in funcs
        )
        aliases = [
            (k, v.function.__name__)
            for k, v in self._functions_map.items()
            if k != v.function.__name__
        ]
        new_functions_map: Dict[str, _FunctionMapValue] = {}
        for i, link in enumerate(self._functions):
            func = link.function
            v = new_functions_map.get(func.__name__)
            if v is None:
                new_functions_map[func.__name__] = _FunctionMapValue(func, i)
            else:
                v.position = None
        for alias, func_name in aliases:
            new_functions_map[alias] = new_functions_map[func_name]
        self._functions_map = new_functions_map

    def modify(self, new_state_type: Optional[Type[State]] = None) -> 'ChainModifier':
        """Returns a :class:`ChainModifier` object.
        """
        return ChainModifier(self, new_state_type)

    def debug(self, func_ref: ChainFunctionRef) -> ChainFunction:
        """Debug a specific function in the chain.

        :param func_ref: a function object or name

        :raises: :exc:`FunctionNotFound` if the function isn't in this chain

        This method wraps the module-level function :func:`state_chain.debug`,
        adding two conveniences.

        First, calling this method not only returns a copy of the function with
        a breakpoint installed, it actually replaces the old function in the
        state chain with the copy. So you can do:

        >>> from types import SimpleNamespace
        >>> def foo(state):
        ...     pass
        ...
        >>> algo = StateChain(SimpleNamespace, functions=[foo])
        >>> algo.debug(foo)
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        Second, you can debug a function by passing its name:

        >>> algo = StateChain(SimpleNamespace, functions=[foo])
        >>> algo.debug('foo')
        <function foo at ...>
        >>> algo.run()                  #doctest: +SKIP
        (Pdb)

        """
        if isinstance(func_ref, str):
            function = self[func_ref]
        elif callable(func_ref):
            function = func_ref
        else:
            raise TypeError("expected str or function, got %r" % type(func_ref))
        try:
            i = self.functions.index(function)
        except ValueError:
            raise FunctionNotFound(function.__name__)
        debugging_function = debug(function)
        self._functions = (
            self._functions[:i] +
            (self._make_chain_link(debugging_function, self._functions[i].exception_pref),) +
            self._functions[i+1:]
        )
        return debugging_function


class FunctionHasMultiplePositions(LookupError):
    """
    Raised by :meth:`StateChain.after` and :meth:`StateChain.before` when the
    function is found multiple times in the state chain.
    """

    def __init__(self, func_name: str) -> None:
        self.func_name = func_name

    def __str__(self) -> str:
        return "The function '%s' appears multiple times in this chain." % self.func_name


class FunctionNotFound(KeyError):
    """
    Raised when a function is not found in a state chain function list.
    Subclass of :exc:`KeyError`.
    """

    def __init__(self, func_name: str) -> None:
        self.func_name = func_name

    def __str__(self) -> str:
        return "The function '%s' isn't in this state chain." % self.func_name


class ChainModifier:
    """This class facilitates the safe modification of a :class:`StateChain`.

    Note that this class doesn't actually alter the given chain, it only returns
    a modified copy of that chain.

    """

    __slots__ = ('new_chain', 'old_functions', 'old_exception_prefs', 'old_aliases')

    def __init__(self, chain: StateChain, new_state_type: Optional[Type[State]] = None):
        new_state_type = new_state_type or chain.state_type
        self.new_chain = StateChain(new_state_type, raise_immediately=chain.raise_immediately)
        self.new_chain.__dict__ = chain.__dict__
        self.old_functions = OrderedDict((f.__name__, f) for f in chain.functions)
        self.old_exception_prefs = {
            link.function.__name__: link.exception_pref for link in chain._functions
        }
        aliases: Dict[str, str] = {}
        for k, v in chain._functions_map.items():
            func_name = v.function.__name__
            if k != func_name:
                if func_name in aliases:
                    aliases[func_name] += ' ' + k
                else:
                    aliases[func_name] = k
        self.old_aliases = aliases

    def add(
        self,
        func_ref: ChainFunctionRef,
        exception: Optional[ExceptionPref] = None,
        alias: Optional[str] = None,
    ) -> 'ChainModifier':
        """Append a function to the modified chain.

        :param func_ref: the function to add, either a function object or the name
            of a function present in the original chain

        :param exception: see :meth:`StateChain.add`

        :raises: :exc:`FunctionNotFound` if `func_ref` is a string that doesn't
            match any function name from the original chain

        """
        if isinstance(func_ref, str):
            try:
                func = self.old_functions[func_ref]
            except KeyError:
                func = self.new_chain[func_ref]
        elif callable(func_ref):
            func = func_ref
        else:
            raise TypeError("expected a string or function, got " + repr(type(func_ref)))
        self.new_chain.add(func, exception=exception, alias=alias)
        self.old_functions.pop(func.__name__, None)
        return self

    def drop(self, func_name: str) -> 'ChainModifier':
        """Skip a function present in the original chain.
        """
        try:
            self.old_functions.pop(func_name)
        except KeyError:
            raise FunctionNotFound(func_name)
        self.old_exception_prefs.pop(func_name)
        self.old_aliases.pop(func_name, None)
        return self

    def end(self) -> StateChain:
        """Returns the modified copy of the original chain.
        """
        if self.old_functions:
            raise IncompleteModification(
                [f.__name__ for f in self.old_functions.values()]
            )
        return self.new_chain

    def keep(self, func_name: str) -> 'ChainModifier':
        """Add a function from the original chain.

        This method copies the function's exception preference and aliases from
        the original chain.
        """
        try:
            exception_pref = self.old_exception_prefs[func_name]
        except KeyError:
            raise FunctionNotFound(func_name)
        alias = self.old_aliases.get(func_name, None)
        self.add(func_name, exception_pref, alias)
        return self

    def replace(
        self,
        func_name: str,
        new_func_ref: ChainFunctionRef,
        exception: Optional[ExceptionPref] = None,
        alias: Optional[str] = None,
    ) -> 'ChainModifier':
        """Replace a function present in the original chain.

        This method copies the function's exception preference and aliases from
        the original chain, unless you provide new values. You can pass the
        empty string as the `alias` argument to disable copying the old aliases
        without adding a new one.
        """
        if exception is None:
            exception = self.old_exception_prefs.get(func_name)
        if alias is None:
            alias = self.old_aliases.get(func_name, None)
        self.drop(func_name)
        self.add(new_func_ref, exception, alias)
        return self


class IncompleteModification(Exception):
    """
    Raised by :class:`ChainModifier.end` when one or more functions from the
    original chain has neither been dropped nor added to the modified chain.
    """

    def __init__(self, func_names: Iterable[str]) -> None:
        self.func_names = func_names

    def __str__(self) -> str:
        return (
            "The following functions have neither been dropped nor added to the "
            "modified chain: %s" % ', '.join(self.func_names)
        )


def call(
    function: Callable[..., T],
    state: Any,
    function_signature: Optional[Signature] = None,
) -> T:
    """Call `function` with argument values taken from the attributes of the `state` object.

    :raises: :exc:`StateLookupError`, if a required argument isn't in the state
    """
    if function_signature is None:
        function_signature = signature(function)
    missing = None
    args = []
    kwargs = {}
    for param in function_signature.parameters.values():
        name, kind = param.name, param.kind
        if hasattr(state, name) or name == 'state':
            value = state if name == 'state' else getattr(state, name)
            if kind in (kind.POSITIONAL_ONLY, kind.POSITIONAL_OR_KEYWORD):
                args.append(value)
            elif kind == kind.KEYWORD_ONLY:
                kwargs[name] = value
        elif param.default is Parameter.empty:
            if kind in (kind.VAR_POSITIONAL, kind.VAR_KEYWORD):
                pass
            else:
                if missing is None:
                    missing = []
                missing.append(name)
    if missing:
        raise StateLookupError(function, missing)
    return function(*args, **kwargs)


class StateLookupError(Exception):
    """
    Raised by :func:`call` when one or more of a chain function's arguments
    aren't available in the state.
    """

    def __init__(self, function: Callable, missing_arguments: List[str]) -> None:
        self.function = function
        self.missing_arguments = missing_arguments

    def __str__(self) -> str:
        missing = self.missing_arguments
        return (
            f"{self.function.__name__}() missing {len(missing)} required "
            f"argument{'s' if len(missing) != 1 else ''}: "
            f"{', '.join(map(repr, missing))}"
        )


def debug(function: Func) -> Func:
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
    method :meth:`StateChain.debug` for an explanation of how this situation
    arises with the :mod:`state_chain` module.

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

    function = cast(FunctionType, function)

    # Build bytecode for a set_trace call.
    # ====================================

    codes = (
        ('LOAD_CONST', 0),
        ('LOAD_CONST', None),
        ('IMPORT_NAME', 'pdb'),
        ('STORE_GLOBAL', 'pdb'),
        ('LOAD_GLOBAL', 'pdb'),
        ('LOAD_ATTR', 'set_trace'),
        ('CALL_FUNCTION', 0),
        ('POP_TOP', 0),
    )

    new_names = function.__code__.co_names
    new_consts = function.__code__.co_consts
    new_code = b''
    addr_pad = 0

    for name, arg_obj in codes:
        # Since Python 3.6, all instructions use exactly two bytes.
        addr_pad += 2
        op = opcode.opmap[name]
        if op in opcode.hasconst:
            if arg_obj not in new_consts:
                new_consts += (arg_obj,)
            arg = new_consts.index(arg_obj)
        elif op in opcode.hasname:
            if arg_obj not in new_names:
                new_names += (arg_obj,)
            arg = new_names.index(arg_obj)
        elif isinstance(arg_obj, int):
            arg = arg_obj
        else:
            raise TypeError(type(arg_obj))
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

    if sys.version_info >= (3, 8):
        new_code_object = function.__code__.replace(
            co_code=new_code,
            co_consts=new_consts,
            co_names=new_names,
            co_lnotab=new_lnotab,
        )
    else:
        new_code_object = CodeType(
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
    new_function = FunctionType(
        new_code_object,
        function.__globals__,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )

    return cast(Func, new_function)
