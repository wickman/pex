PEX
===
.. image:: https://travis-ci.org/pantsbuild/pex.svg?branch=master
    :target: https://travis-ci.org/pantsbuild/pex

pex is a library for generating .pex (Python EXecutable) files,
executable Python environments in the spirit of `virtualenvs <http://virtualenv.org>`_.
They are designed to make deployment of Python applications as simple as ``cp``.
pex is licensed under the Apache2 license.

.pex files can be built using the ``pex`` tool bundled with pex.  Build systems such as `Pants
<http://pantsbuild.github.io/>`_ and `Buck <http://facebook.github.io/buck/>`_ also
support building .pex files directly.


Installation
============

To install pex, simply

.. code-block:: bash

    $ pip install pex

You can also "install" pex by using pex to build itself in a git clone using tox:

.. code-block:: bash

    $ tox -e package

This will build a pex binary in ``dist/pex`` that can be copied onto your ``$PATH``.


Documentation
=============

More documentation about pex, building .pex files, and how .pex files work
is available at http://pex.rtfd.org.


Development
===========

pex uses `tox <https://testrun.org/tox/latest/>`_ for test and development automation.  To run
the test suite, just invoke tox:

.. code-block:: bash

    $ tox

To generate a coverage report (with more substantial integration tests):

.. code-block:: bash

   $ tox -e coverage

To check style and sort ordering:

.. code-block:: bash

   $ tox -e style,isort-check

To generate and open local sphinx documentation:

.. code-block:: bash

   $ tox -e docs

To run the 'pex' tool from source (for 3.4, use 'py34-run'):

.. code-block:: bash

   $ tox -e py27-run -- <cmdline>


Contributing
============

To contribute, follow these instructions: http://pantsbuild.github.io/howto_contribute.html
