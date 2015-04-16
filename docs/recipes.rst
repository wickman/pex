.. _recipes:

******************
Common pex recipes
******************

Freezing the current environment
--------------------------------

If you are in a virtualenv with a set of requirements, you can easily recreate it as a pex file
using ``pex -r`` and ``pip freeze``:

    $ pex -r <(pip freeze) -o virtualenv.pex

Dropping into the interpreter
-----------------------------

Specifying entry points
-----------------------

Building multi-platform PEX files
---------------------------------

Accessing zipped resources from within a PEX
--------------------------------------------

Getting PEX coverage
--------------------

Doing PEX profiling
-------------------

