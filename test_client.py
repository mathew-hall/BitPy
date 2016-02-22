import BitPy.client
import BitPy.torrents
import logging

import unittest
import struct
from twisted.test import proto_helpers
from nose.tools import assert_equals
from nose.tools import assert_true


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
	assert_equals(client.torrents[torrent.info_hash]['tracker id'], 'dead beef face')
	
def test_client_updates_peer_list():
	client = BitPy.client.Client()
	torrent = get_torrent()
	client.add_torrent(torrent)
	response = {u'peers': u"\xcaSm\xcd\xd5\x80.\xa0\x04p\xc8\xd5\xd5\xde\x96\xb2l\xcfU_\xb8\xc6\x1bE_\x18\xb5\xdb\x96'l=\xaal\x1a\xe2b\xf6\xec\xa5\xa7\xe1\xc6\x1bU\x8b\xd9 O!\xc9\xcf\x12n\xc2\xe2\x9b\t\xde\xa7", u'interval': 1800, u'complete': 3837, u'incomplete': 98}
	client.handle_tracker_response(torrent.info_hash,response)
	assert_equals(len(client.torrents[torrent.info_hash]['peers']), 10)

class TestClient(unittest.TestCase):
	def setUp(self):
		self.client = BitPy.client.Client()
		self.torrent = get_torrent()
		self.client.add_torrent(self.torrent)
		factory = BitPy.client.PeerClientFactory(self.client)
		
		self.proto = factory.buildProtocol(('127.0.0.1', 0))
		self.tr = proto_helpers.StringTransport()
		
		self.proto.makeConnection(self.tr)
		self.proto.dataReceived(self.get_handshake(info_hash=self.torrent.info_hash))
		assert_equals(self.proto.connected, 1)
#		assert_equals(self.proto.state, 'ACTIVE')
		
	def get_handshake(self,info_hash=('A'*20), peer_id=('B'*20)):
		return "".join(['\x03', 'abc', '\x00'*8, info_hash, peer_id])
	
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
		assert_true('B'*20 in self.client.torrents[self.torrent.info_hash]['choked_peers'])
	
	def test_unchoke(self):
		self.send('\x00')
		assert_true('B'*20 in self.client.torrents[self.torrent.info_hash]['choked_peers'])
		
		self.send('\x01')
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
		assert_true('B'*20 not in self.client.torrents[self.torrent.info_hash]['choked_peers'])
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
		
	def test_have(self):
		self.send('\x05' + struct.pack('!I', 1234))
		assert_equals(self.proto.connected, 1)
		assert_equals(self.proto.state, 'ACTIVE')
		
	def test_store(self):
		self.send('\x07' + '\x00\x00\x00\x00' + '\x00\x00\x00\x00' + 'my bytes go here')
		assert_equals(self.client.torrents[self.torrent.info_hash]['pieces'][0], {0:'my bytes go here'})
	
	