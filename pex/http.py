from abc import abstractmethod
import contextlib
import io
import os
import shutil

from .compatibility import AbstractClass

try:
  import requests
except ImportError:
  requests = None

try:
  from cachecontrol import CacheControl
  from cachecontrol.caches import FileCache
except ImportError:
  CacheControl = FileCache = None


class Context(AbstractClass):
  class Error(Exception): pass

  REGISTRY = []

  @classmethod
  def register(cls, context):
    if not isinstance(context, cls):
      raise TypeError('Context must be a Context, got %s' % type(context))
    cls.REGISTRY.insert(0, context)

  @classmethod
  def get(cls):
    for context_class in cls.REGISTRY:
      try:
        return context_class()
      except cls.Error:
        continue
    raise cls.Error('Could not initialize a request context.')

  @abstractmethod
  def open(self, link):
    """Return an open file-like object to the :link:`Link`."""
    pass

  def read(self, link):
    with contextlib.closing(self.open(link)) as fp:
      return fp.read()

  def fetch(self, link, into=None):
    target = os.path.join(into or safe_mkdtemp(), link.filename)

    if os.path.exists(target):
      # Assume that if the local file already exists, it is safe to use.
      return target

    target_tmp = '%s.%s' % (target, uuid.uuid4())
    with contextlib.closing(self.open(link)) as in_fp:
      with open(target_tmp, 'wb') as out_fp:
        shutil.copyfileobj(in_fp, out_fp)

    os.rename(target_tmp, target)
    return target


class UrllibContext(Context):
  def open(self, link):
    return urllib_request.urlopen(link.url)


Context.register(UrllibContext)


# TODO(wickman) Implement fetch using stream=True and request.raw
class RequestsContext(Context):
  def __init__(self, session=None):
    self._session = session or requests.session()

  def open(self, link):
    try:
      return io.BytesIO(requests.get(link.url).content)
    except requests.exceptions.RequestException as e:
      raise self.Error(e)


if requests:
  Context.register(RequestsContext)


class CachedRequestsContext(RequestsContext):
  DEFAULT_CACHE = '~/.pex/cache'

  def __init__(self, cache=None):
    self._cache = os.path.realpath(os.path.expanduser(self.cache or DEFAULT_CACHE))
    super(CachedRequestsContext, self).__init__(
        CacheControl(requests.session(), cache=FileCache(self._cache)))


if CacheControl:
  Context.register(CachedRequestsContext)
