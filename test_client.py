import BitPy.client
import BitPy.torrents
import logging

import unittest
import struct
from twisted.test import proto_helpers
from nose.tools import assert_equals
from nose.tools import assert_true
from nose.tools import assert_false

from twisted.internet import reactor
from twisted.internet.protocol import Factory, Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint


def get_torrent():
	return BitPy.torrents.load_torrent_file("ubuntu-15.10-desktop-amd64.iso.torrent")

def test_client_generates_peer_id():
	client = BitPy.client.Client()
	assert_equals(len(client.peer_id), 20)
	
def xtest_client_pings_tracker():
	client = BitPy.client.Client()
	torrent = get_torrent()
	res = client.tracker_event(torrent)
	assert_true('failure reason' not in res)
	assert_true('warning message' not in res)

def test_client_updates_tracker_id():
	client = BitPy.client.Client()
	torrent = get_torrent()
	client.add_torrent(torrent)
	client.handle_tracker_response(torrent.info_hash,{'tracker id':'dead beef face', 'info hash':torrent.info_hash})
	assert_equals(client.torrents[torrent.info_hash].tracker_id, 'dead beef face')
	
def test_client_updates_peer_list():
	client = BitPy.client.Client()
	torrent = get_torrent()
	client.add_torrent(torrent)
	response = {u'peers': u"\xcaSm\xcd\xd5\x80.\xa0\x04p\xc8\xd5\xd5\xde\x96\xb2l\xcfU_\xb8\xc6\x1bE_\x18\xb5\xdb\x96'l=\xaal\x1a\xe2b\xf6\xec\xa5\xa7\xe1\xc6\x1bU\x8b\xd9 O!\xc9\xcf\x12n\xc2\xe2\x9b\t\xde\xa7", u'interval': 1800, u'complete': 3837, u'incomplete': 98}
	client.handle_tracker_response(torrent.info_hash,response)
	assert_equals(len(client.torrents[torrent.info_hash].peers), 10)


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
		assert_equals(self.download.get_bitfield(),['\x00'])
		self.download.store_piece(0,0,'a'*10)
		assert_equals(self.download.get_bitfield(), [chr(0b10000000)])
		
	def test_progress(self):
		self.torrent.info.pieces = ['a'*20, 'b'*20]
		self.torrent.info_piece_length=5
		assert_equals(self.download.get_progress(),0)
		self.download.store_piece(0,0,'a'*5)
		assert_equals(self.download.get_progress(),0.5)
		self.download.store_piece(1,0,'a'*5)
		assert_equals(self.download.get_progress(),1)

class TestClient(unittest.TestCase):
	def setUp(self):
		self.client = BitPy.client.Client()
		self.torrent = get_torrent()
		self.client.add_torrent(self.torrent)
		factory = BitPy.client.PeerClientFactory(self.client,self.torrent.info_hash)
		
		self.proto = factory.buildProtocol(('127.0.0.1', 0))
		self.tr = proto_helpers.StringTransport()
		
		self.proto.makeConnection(self.tr)
		self.proto.dataReceived(self.get_handshake(info_hash=self.torrent.info_hash))
		assert_equals(self.proto.connected, 1)
		assert_equals(self.tr.value(), self.get_handshake(info_hash=self.torrent.info_hash,peer_id=self.client.peer_id))
		assert_equals(self.proto.peer.peer_id, 'B'*20)
#		assert_equals(self.proto.state, 'ACTIVE')
		
	def get_handshake(self,info_hash=('A'*20), peer_id=('B'*20)):
		return "".join(['\x13', 'BitTorrent protocol', '\x00'*8, info_hash, peer_id])
	
	def send(self,data):
		self.proto.dataReceived(struct.pack('!I', len(data)) + data)
		
	def test_keepalive(self):
		self.send("")
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
	
	def test_choke(self):
		self.send('\x00')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
		assert_true(self.client.get_peer(self.torrent.info_hash,'B'*20).choked)
	
	def test_unchoke(self):
		self.send('\x00')
		assert_true(self.client.get_peer(self.torrent.info_hash,'B'*20).choked)
		
		self.send('\x01')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
		assert_false(self.client.get_peer(self.torrent.info_hash,'B'*20).choked)
		self.send('\x01')
	
	def test_interested(self):
		self.send('\x02')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
	
	def test_not_interested(self):
		self.send('\x03')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
	
	def test_have(self):
		self.send('\x04' + struct.pack('!I', 1234))
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
		
	def test_bitfield(self):
		pass
		
	def test_request(self):
		self.send('\x06' + '\x00\x00\x00\x00' + '\x00\x00\x00\x00' + '\x00\x00\x00\x01')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
	
	
	def test_store(self):
		self.torrent.info.piece_length = 25
		self.send('\x07' + '\x00\x00\x00\x00' + '\x00\x00\x00\x00' + 'a'*20)
		assert_equals(self.client.torrents[self.torrent.info_hash].pieces[0][:20], list('a'*20))
	
class TestRemote():
	def test_connect_to_transmission(self):
		import logging
		logging.basicConfig(level=logging.DEBUG)
		client = BitPy.client.Client()
		ubuntu = get_torrent()
		client.add_torrent(ubuntu)
		client.add_peer(ubuntu.info_hash, 'localhost', 1500)
		reactor.connectTCP('localhost', 1500, BitPy.client.PeerClientFactory(client,ubuntu.info_hash))
		reactor.run()
		