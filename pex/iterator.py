import itertools
from abc import abstractmethod

from .compatibility import AbstractClass
from .crawler import Crawler
from .fetcher import PyPIFetcher
from .package import EggPackage, Package, SourcePackage, WheelPackage


class IteratorInterface(AbstractClass):
  @abstractmethod
  def iter(self, req):
    """Return a list of packages that satisfy the requirement in best match order."""
    pass


class Iterator(IteratorInterface):
  """A requirement iterator."""

  DEFAULT_PACKAGE_PRECEDENCE = (
      WheelPackage,
      EggPackage,
      SourcePackage,
  )

  @classmethod
  def package_type_precedence(cls, package, precedence=DEFAULT_PACKAGE_PRECEDENCE):
    for rank, package_type in enumerate(reversed(precedence)):
      if isinstance(package, package_type):
        return rank
    # If we do not recognize the package, it gets lowest precedence
    return -1

  @classmethod
  def package_precedence(cls, package, precedence=DEFAULT_PACKAGE_PRECEDENCE):
    return (
        package.version,  # highest version
        cls.package_type_precedence(package, precedence=precedence),  # type preference
        package.local)  # prefer not fetching over the wire

  def __init__(self,
               fetchers=None,
               crawler=None,
               precedence=None,
               follow_links=False):
               #allow_external=frozenset(),
               #allow_all_external=False):
    self._crawler = crawler or Crawler()
    self._fetchers = fetchers or [PyPIFetcher()]
    self._precedence = precedence or self.DEFAULT_PACKAGE_PRECEDENCE
    self.__follow_links = follow_links
    #self._allow_external = allow_external
    #self._allow_all_external = allow_all_external

  def _follow_links(self, req):
    #if self._allow_all_external:
    #  return True
    #return req.key in self._allow_external
    return self.__follow_links

  def _translate_href(self, href):
    package = Package.from_href(href)
    # Restrict this to a package found in the package precedence list, so that users of
    # obtainers can restrict which distribution formats they support.
    if any(isinstance(package, package_type) for package_type in self._precedence):
      return package

  def _iter_requirement_urls(self, req):
    return itertools.chain.from_iterable(fetcher.urls(req) for fetcher in self._fetchers)

  def _iter_unordered(self, req):
    url_iterator = self._iter_requirement_urls(req)
    crawled_url_iterator = self._crawler.crawl(url_iterator, follow_links=self._follow_links(req))
    for package in filter(None, map(self._translate_href, crawled_url_iterator)):
      if package.satisfies(req):
        yield package

  def _sort(self, package_list):
    key = lambda package: self.package_precedence(package, self._precedence)
    return sorted(package_list, key=key, reverse=True)

  def iter(self, req):
    """Return a list of packages that satisfy the requirement in best match order."""
    for package in self._sort(self._iter_unordered(req)):
      yield package
