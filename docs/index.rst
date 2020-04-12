state_chain.py
==============

.. automodule:: state_chain
    :members:
    :member-order: bysource
    :special-members:
    :exclude-members: __weakref__


Migrating from 1.x
------------------

Version 2.0 of the ``state_chain`` module includes several breaking changes.

1\) The ways to create and initialize a state chain have changed. The
``StateChain.from_dotted_name`` constructor no longer exists, and the default
``StateChain`` constructor no longer takes a variable number of arguments.

.. code-block:: diff

    -chain = StateChain.from_dotted_name(...)
    +chain = StateChain()
    +
    +@chain.add
    +def foo(...):
    +    ...
    +
    +@chain.add
    +def bar(...):
    +    ...

.. code-block:: diff

    -chain = StateChain(foo, bar)
    +chain = StateChain(functions=[foo, bar])

2\) The :meth:`StateChain.run` method no longer accepts a variable number of arguments.

.. code-block:: diff

    -chain.run(x=0, _raise_immediately=True, _return_after='foo')
    +from state_chain import Object
    +chain.run(Object(x=0), raise_immediately=True, return_after='foo')

3\) Modifying the state by returning dictionaries is no longer supported. You
have to explicitly modify the :obj:`state` object instead.

.. code-block:: diff

    -def foo():
    -    return {'x': 0}
    +def foo(state):
    +    state.x = 0
