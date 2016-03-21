import mock
from nose.twistedtools import reactor, deferred
import nose.twistedtools
import BitPy.client
import BitPy.torrents
import logging


import unittest
import struct
from twisted.test import proto_helpers
from nose.tools import assert_equals
from nose.tools import assert_true
from nose.tools import assert_false

from twisted.internet.protocol import Factory, Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet import defer


def get_torrent():
	return BitPy.torrents.load_torrent_file("ubuntu-15.10-desktop-amd64.iso.torrent")
	
class TestTracker():
	def setUp(self):
		self.torrent = get_torrent()
		self.client = BitPy.client.Client(self.torrent)

	def test_client_generates_peer_id(self):
		assert_equals(len(self.client.peer_id), 20)

	def test_client_pings_tracker(self):
		res = self.client.tracker_event()
		assert_true('failure reason' not in res)
		assert_true('warning message' not in res)

	def test_client_updates_tracker_id(self):
		self.client.handle_tracker_response({'tracker id':'dead beef face', 'info hash':self.torrent.info_hash})
		assert_equals(self.client.tracker_id, 'dead beef face')

	def test_client_updates_peer_list(self):
		response = {u'peers': u"\xcaSm\xcd\xd5\x80.\xa0\x04p\xc8\xd5\xd5\xde\x96\xb2l\xcfU_\xb8\xc6\x1bE_\x18\xb5\xdb\x96'l=\xaal\x1a\xe2b\xf6\xec\xa5\xa7\xe1\xc6\x1bU\x8b\xd9 O!\xc9\xcf\x12n\xc2\xe2\x9b\t\xde\xa7", u'interval': 1800, u'complete': 3837, u'incomplete': 98}
		self.client.handle_tracker_response(response)
		assert_equals(len(self.client.peers), 10)

class TestClientBeaviour(unittest.TestCase):
	def setUp(self):
		self.torrent = get_torrent()
		self.client = BitPy.client.Client(self.torrent)
		response = {u'peers': u"\xcaSm\xcd\xd5\x80.\xa0\x04p\xc8\xd5\xd5\xde\x96\xb2l\xcfU_\xb8\xc6\x1bE_\x18\xb5\xdb\x96'l=\xaal\x1a\xe2b\xf6\xec\xa5\xa7\xe1\xc6\x1bU\x8b\xd9 O!\xc9\xcf\x12n\xc2\xe2\x9b\t\xde\xa7", u'interval': 1800, u'complete': 3837, u'incomplete': 98}
		self.client.handle_tracker_response(response)
		self.client.peers_wanted=5

	@mock.patch('BitPy.client.Client.connect_peer')
	def test_client_connects_to_peers(self,mock):
		self.client.check_peers()
		assert_true(mock.called)



class TestDownload(unittest.TestCase):
	def setUp(self):
		self.torrent = get_torrent()
		self.download = BitPy.client.Download(self.torrent)
		self.torrent.info.piece_length = 50

	def test_empty_progress(self):
		assert_equals(self.download.piece_progress(0), 0)

	def test_full_progress(self):
		self.download.store_piece(0,0,'\x00' * self.torrent.info.piece_length)
		assert_equals(self.download.piece_progress(0), 1)

	def test_full_progress_from_multiple_pieces(self):
		self.download.store_piece(0,0,'\xaa' * 10)
		self.download.store_piece(0,10,'\x01' * (self.torrent.info.piece_length - 10))
		assert_equals(self.download.piece_progress(0), 1)

	def test_partial_progress(self):
		self.download.store_piece(0,0,'\xaa' * 25)
		assert_equals(self.download.piece_progress(0), 0.5)

	def test_bitfield(self):
		self.torrent.info.pieces = ['\x41'*20, '\x42'*20]
		self.torrent.info.piece_length=10
		assert_equals(self.download.bitfield,['\x00'])
		self.download.store_piece(0,0,'a'*10)
		assert_equals(self.download.bitfield, [chr(0b10000000)])

	def test_verify_piece(self):
		self.torrent.info.pieces = ['3495ff69d34671d1e15b33a63c1379fdedd3a32a'.decode('hex')]
		self.torrent.info.piece_length = 10
		self.download.store_piece(0,0,'a'*10)
		assert_true(self.download.have_piece(0))
		self.torrent.info.pieces = ['a'*20]
		assert_false(self.download.have_piece(0))

	def test_progress(self):
		self.torrent.info.pieces = ['a'*20, 'b'*20]
		self.torrent.info_piece_length=5
		assert_equals(self.download.progress,0)
		self.download.store_piece(0,0,'a'*5)
		assert_equals(self.download.progress,0.5)
		self.download.store_piece(1,0,'a'*5)
		assert_equals(self.download.progress,1)

	def test_missing_pieces(self):
		self.torrent.info.pieces = ['3495ff69d34671d1e15b33a63c1379fdedd3a32a'.decode('hex') for _ in range(0,3)]
		self.torrent.info.piece_length=10
		assert_equals(self.download.missing_pieces, [0,1,2])
		self.download.store_piece(0,0,'a'*10)
		assert_equals(self.download.missing_pieces, [1,2])


class TestRemote():
	@deferred()
	def xtest_connect_to_transmission(self):
		import logging
		logging.basicConfig(level=logging.DEBUG)
		ubuntu = get_torrent()
		client = BitPy.client.Client(ubuntu)
		peer = client.add_peer('localhost', 1500)
		client.connect_peer(peer)
		d = defer.Deferred()
		def check_bitfield(d):
			assert_true(any([x>0 for x in peer.bitfield]))
		reactor.callLater(10, d.callback,'f')
		d.addCallback(check_bitfield)
		return d
		#reactor.run()
