from nose.twistedtools import reactor, deferred
import nose.twistedtools
import BitPy.client
import BitPy.protocol
import BitPy.torrents
import logging


import unittest
import struct
from twisted.test import proto_helpers
from nose.tools import assert_equals
from nose.tools import assert_true
from nose.tools import assert_false

import tempfile

def get_torrent():
	return BitPy.torrents.load_torrent_file("ubuntu-15.10-desktop-amd64.iso.torrent")

class TestClient(unittest.TestCase):
	def setUp(self):
		self.torrent = get_torrent()
		self.torrent.info.pieces = ['3495ff69d34671d1e15b33a63c1379fdedd3a32a'.decode('hex') for _ in range(0,3)]
		self.torrent.info.piece_length=10
		self.torrent.info.size = 30

		self.client = BitPy.client.Client(self.torrent, file=tempfile.SpooledTemporaryFile())
		factory = BitPy.protocol.PeerClientFactory(self.client)

		self.proto = factory.buildProtocol(('127.0.0.1', 0))
		self.tr = proto_helpers.StringTransport()

		self.proto.makeConnection(self.tr)
		self.proto.dataReceived(self.get_handshake(info_hash=self.torrent.info_hash))
		assert_equals(self.proto.connected, 1)
		assert_equals(self.tr.value(), self.get_handshake(info_hash=self.torrent.info_hash,peer_id=self.client.peer_id))
		assert_equals(self.proto.peer.peer_id, 'B'*20)
		assert_equals(len(self.client.connected_peers),1)
		assert_equals(self.proto.state, 'ACTIVE')

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
		assert_true(self.client.get_peer('B'*20).choked)

	def test_unchoke(self):
		self.send('\x00')
		assert_true(self.client.get_peer('B'*20).choked)

		self.send('\x01')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
		assert_false(self.client.get_peer('B'*20).choked)
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
		self.send('\x04' + struct.pack('!I', 0))
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')

	def test_bitfield(self):
		self.send('\x05' + '\xf0')
		assert_equals(self.proto.peer.bitfield, ['\xf0'])

	def test_request(self):
		self.send('\x06' + '\x00\x00\x00\x00' + '\x00\x00\x00\x00' + '\x00\x00\x00\x01')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
		assert_equals(self.client.connected_peers[0].requests[0], (0,0,1))


	def test_store(self):
		self.torrent.info.piece_length = 10
		self.send('\x07' + '\x00\x00\x00\x00' + '\x00\x00\x00\x00' + 'a'*10)
		assert_equals(self.client.download.get_piece(0), 'a'*10)

	def test_handle_request(self):
		self.send('\x07' + '\x00\x00\x00\x00' + '\x00\x00\x00\x00' + 'a'*10)
		self.send('\x06' + struct.pack('!III',0,0,10))
		peer = self.client.connected_peers[0]
		self.tr.clear()
		self.client.handle_request(peer, peer.requests[0])
		response = '\07'+struct.pack('!II',0,0)+'a'*10
		assert_equals(self.tr.value(),struct.pack('!I',len(response)) + response)

	def test_get_pieces_to_send(self):
		self.send('\x07' + '\x00\x00\x00\x00' + '\x00\x00\x00\x00' + 'a'*10)
		self.send('\x07' + '\x00\x00\x00\x01' + '\x00\x00\x00\x00' + 'a'*10)
		self.send('\x07' + '\x00\x00\x00\x02' + '\x00\x00\x00\x00' + 'a'*10)
		peer = self.client.connected_peers[0]
		assert_equals(peer.bitfield,['\x00'])
		assert_equals(list(self.client.get_pieces_to_send(peer)), [0,1,2])

	def test_get_pieces_to_request(self):
		peer = self.client.connected_peers[0]
		[peer.set_have(piece) for piece in range(0,4)]
		assert_equals(self.client.download.bitfield, ['\x00'])
		assert_equals(list(self.client.get_pieces_to_request(peer)), [0,1,2,3])
