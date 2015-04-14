#!/bin/bash

coverage run -p -m py.test tests
coverage run -p -m pex.bin.pex -v --help >&/dev/null
coverage run -p -m pex.bin.pex -v -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v requests -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v -s . setuptools -- scripts/do_nothing.py
