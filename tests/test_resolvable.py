# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.resolvable import (
    Resolvable,
    ResolvablePackage,
    ResolvableRepository,
    ResolvableRequirement
)


def test_noop():
  Resolvable
  ResolvablePackage
  ResolvableRepository
  ResolvableRequirement
