from contextlib import contextmanager
import hashlib

from pex.http import (
    CachedRequestsContext,
    Context,
    RequestsContext,
    StreamFilelike,
    UrllibContext,
)
from pex.link import Link

from twitter.common.contextutil import temporary_file
import responses
import requests
import pytest


BLOB = b'random blob of data'


def make_md5(blob):
  md5 = hashlib.md5()
  md5.update(blob)
  return md5.hexdigest()


@contextmanager
def make_url(blob, md5_fragment=None):
  url = 'http://pypi.python.org/foo.tar.gz'
  if md5_fragment:
    url += '#md5=%s' % md5_fragment

  responses.add(
      responses.GET,
      url,
      status=200,
      body=blob,
      content_type='application/x-compressed')
  
  yield url


@responses.activate
def test_stream_filelike_with_correct_md5():
  with make_url(BLOB, make_md5(BLOB)) as url:
    request = requests.get(url)
    filelike = StreamFilelike(request, Link.wrap(url))
    assert filelike.read() == BLOB
  

@responses.activate
def test_stream_filelike_with_incorrect_md5():
  with make_url(BLOB, 'f' * 32) as url:
    request = requests.get(url)
    filelike = StreamFilelike(request, Link.wrap(url))
    with pytest.raises(Context.Error):
      filelike.read()


@responses.activate
def test_stream_filelike_without_md5():
  with make_url(BLOB) as url:
    request = requests.get(url)
    filelike = StreamFilelike(request, Link.wrap(url))
    assert filelike.read() == BLOB


@responses.activate
def test_requests_context():
  context = RequestsContext(verify=False)

  with make_url(BLOB, make_md5(BLOB)) as url:
    assert context.read(Link.wrap(url)) == BLOB
  
  with make_url(BLOB, make_md5(BLOB)) as url:
    filename = context.fetch(Link.wrap(url))
    with open(filename, 'rb') as fp:
      assert fp.read() == BLOB
  
  # test local reading
  with temporary_file() as tf:
    tf.write('goop')
    tf.flush()
    assert context.read(Link.wrap(tf.name)) == 'goop'
    
    