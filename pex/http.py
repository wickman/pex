from abc import abstractmethod
import contextlib
import hashlib
import io
import os
import shutil
import uuid

from .compatibility import AbstractClass, PY3
from .common import safe_mkdtemp, safe_open
from .tracer import TRACER

try:
  import requests
except ImportError:
  requests = None

try:
  from cachecontrol import CacheControl
  from cachecontrol.caches import FileCache
except ImportError:
  CacheControl = FileCache = None

if PY3:
  import urllib.request as urllib_request
else:
  import urllib2 as urllib_request


class Context(AbstractClass):
  class Error(Exception): pass

  REGISTRY = []

  @classmethod
  def register(cls, context):
    #if not isinstance(context, Context):
    #  raise TypeError('Context must be a Context, got %s' % (context.__mro__,))
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

    with TRACER.timed('Fetching %s' % link.url, V=2):
      target_tmp = '%s.%s' % (target, uuid.uuid4())
      with contextlib.closing(self.open(link)) as in_fp:
        with safe_open(target_tmp, 'wb') as out_fp:
          shutil.copyfileobj(in_fp, out_fp)

    os.rename(target_tmp, target)
    return target


class UrllibContext(Context):
  def open(self, link):
    return urllib_request.urlopen(link.url)


Context.register(UrllibContext)


class StreamFilelike(object):
  """A file-like object wrapper for requests streams that can validate md5s."""

  def __init__(self, request, link, chunk_size=16*1024):
    self._iterator = request.iter_content(chunk_size)
    self._bytes = b''
    self._link = link
    self._md5 = link.md5
    self._hash = hashlib.md5()

  def read(self, length=None):
    while length is None or len(self._bytes) < length:
      try:
        next_chunk = next(self._iterator)
        if self._md5:
          self._hash.update(next_chunk)
        self._bytes += next_chunk
      except StopIteration:
        self._validate()
        break
    chunk, self._bytes = self._bytes[:length], self._bytes[length:]
    return chunk

  def _validate(self):
    if self._md5:
      if self._md5 != self._hash.hexdigest():
        raise Context.Error('%s failed checksum!' % (self._link.url))
      else:
        TRACER.log('Validated %s (md5=%s)' % (self._link.filename, self._link.md5), V=3)

  def close(self):
    pass


class RequestsContext(Context):
  """A requests-based Context."""

  def __init__(self, session=None, verify=True):
    self._verify = verify
    self._session = session or requests.session()

  def open(self, link):
    # requests does not support file:// -- so we must short-circuit manually
    if link.local:
      return open(link.path, 'rb')
    try:
      return StreamFilelike(requests.get(link.url, verify=self._verify, stream=True), link)
    except requests.exceptions.RequestException as e:
      raise self.Error(e)


if requests:
  Context.register(RequestsContext)


class CachedRequestsContext(RequestsContext):
  """A requests-based Context with CacheControl support."""

  DEFAULT_CACHE = '~/.pex/cache'

  def __init__(self, cache=None, **kw):
    self._cache = os.path.realpath(os.path.expanduser(cache or self.DEFAULT_CACHE))
    super(CachedRequestsContext, self).__init__(
        CacheControl(requests.session(), cache=FileCache(self._cache)), **kw)


if CacheControl:
  Context.register(CachedRequestsContext)
