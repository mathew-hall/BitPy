import random
import SocketServer
import requests
import bencode
import logging
import StringIO
import struct
import math

from twisted.internet.protocol import Factory
from twisted.protocols.basic import Int32StringReceiver
from twisted.internet import reactor

class Download():
	logger = logging.getLogger(__name__)
	
	def __init__(self, torrent):
		self.torrent = torrent
		self.peers = []
		self.pieces = {}
		self.piece_state = {}
		self.tracker_id = None
		self.connected_peers = []
	
	def piece_progress(self, index):
		piece_size = self.torrent.info.piece_length
		if index not in self.piece_state:
			return 0
		
		current_end_byte = 0
		missing = 0
		for (start,next_byte) in self.piece_state[index]:
			missing = missing + start - current_end_byte
			current_end_byte = next_byte

		missing = missing + piece_size - current_end_byte
		
		return (piece_size - missing) / float(piece_size)
		
	def store_piece(self, index, begin, data):
		piece_size = self.torrent.info.piece_length
		data_size = len(data)
		chunk = self.pieces.get(index, list('\x00' * piece_size))
		chunk[begin:begin+data_size] = data
		self.pieces[index] = chunk
		
		self.logger.debug("Storing %d bytes at %d; chunk is now %s", data_size,begin,chunk)
		
		state = self.piece_state.get(index, [])
		state.append((begin, begin+data_size))
		state.sort()
		
		self.logger.debug("State is %s", state)
		
		self.piece_state[index] = state

class Peer():
	def __init__(self, host, port, peer_id=None, pieces=0):
		self.peer_id = peer_id
		self.host = host
		self.port = port
		self.bitfield = '\x00' * int(math.ceil(pieces / 8.0))
		self.choked = True
		self.interested = False
		self.requests = []
	
	def set_have(self, piece):
		index = piece // 8
		bit   = 8 - (piece % 8)
		self.bitfield[index] = self.bitfield[index] & (1 << bit)
		
	def set_bitfield(self, bitfield):
		self.bitfield = list(bitfield)
	
	def add_request(self, index, begin, length):
		self.requests.append((index,begin,length))
	
	def __repr__(self):
		return repr({'peer id': self.peer_id, 'host':self.host, 'port':self.port, 'bitfield': self.bitfield, 'choked':self.choked, 'interested': self.interested})

class Client():

	logger = logging.getLogger('client')
	
	
	def __init__(self, wanted = None):
		self.uploaded = 0
		self.downloaded = 0
		self.peers_wanted = wanted or 10
		self.peer_id = ''.join(chr(random.randint(0,255)) for _ in range(20))
		self.key = ''.join(chr(random.randint(0,255)) for _ in range(20))
		self.torrents = {}

	
	def start(self):
		reactor.listenTCP(8123, PeerClientFactory(self))
		reactor.run()
	
	
	def add_torrent(self,torrent):
		self.torrents[torrent.info_hash] = Download(torrent)

	
	def get_needed(self,torrent):
		return 0
	
	def handle_tracker_response(self,info_hash,message):
		self.logger.info("Tracker state update for %s",str(message))
		self.torrents[info_hash].tracker_id = message.get('tracker id',None)
		peerlist = message.get('peers',"")
		for start in xrange(0,len(peerlist),6):
			peer = [str(ord(c)) for c in list(peerlist[start:start+6])]
			host = ".".join(peer[0:4])
			port = int(peer[4]) << 8 | int(peer[5])
			self.add_peer(info_hash, host,port)
		self.logger.info("Torrent state is now %s", str(self.torrents[info_hash]))
		
	def store_piece(self,info_hash,index,begin,data):
		index_entry = self.torrents[info_hash].pieces.get(index,{})
		index_entry[begin] = data
		self.torrents[info_hash].pieces[index] = index_entry
	
	def add_peer(self, info_hash, host, port, peer_id=None, connection=None):
		peer = self.get_peer(info_hash, host=host, port=port, peer_id=peer_id)
		if peer is None:
			peer = Peer(host,port,peer_id,len(self.torrents[info_hash].torrent.info.pieces))
			self.torrents[info_hash].peers.append(peer)
		if connection:
			peer.connection = connection
			self.torrents[info_hash].connected_peers.append(peer)
		if peer_id is not None and (peer.peer_id != peer_id):
			self.logger.warn("Peer %s has changed IDs to %s",repr(peer), repr(peer_id))
			
		return peer
		
	def get_peer(self, info_hash, peer_id=None, host=None, port=None):
		for peer in self.torrents[info_hash].peers:
			if (peer_id is not None and peer.peer_id == peer_id) or (peer.host == host and peer.port == port):
				return peer
		return None
			


	def tracker_event(self, torrent, event=""):
		tracker = torrent.announce
		params={\
			'info_hash':torrent.info_hash, \
			'peer_id':self.peer_id, \
			'port': self.server.server_address[1], \
			'uploaded': self.uploaded, \
			'downloaded': self.downloaded, \
			'compact': 1, \
			'numwant': self.peers_wanted, \
			'key': self.key.encode("hex") \
		}
		
		params['left'] = self.get_needed(torrent.info_hash)
		
		if torrent in self.torrents:
			tracker_id = self.torrents[torrent.info_hash].get('tracker id')
			if tracker_id:
				params['trackerid'] = tracker_id
		if event:
			params['event'] = event
		
		self.logger.info("Pinging tracker at %s with params %s", tracker,params)
		response = requests.get(tracker,params=params)
		if response.status_code != 200:
			return None
		
		result = bencode.bendecode(response.text)
		return result
		




class PeerConnection(Int32StringReceiver):
	logger = logging.getLogger('tcpserver')
	def __init__(self, client):
		self.state = "HANDSHAKE"
		self.preamble_size = 0
		self.client = client
		self.peer = None
	
	def dataReceived(self, recd):
		if self.state == "HANDSHAKE":
			self.recvd = self.recvd + recd
			self.logger.debug("Received data in state %s: %s", self.state, repr(self.recvd))
			if len(self.recvd) >= 1:
				if self.preamble_size == 0:
					pstrlen = ord(self.recvd[0])
					self.preamble_size = pstrlen + 49
				if len(self.recvd) >= self.preamble_size and self.preamble_size != 0:
					preamble = self.recvd[0:self.preamble_size]
					self.recvd = self.recvd[self.preamble_size:]
					self.handle_HANDSHAKE(preamble)
					self.state = "ACTIVE"
		else:
			Int32StringReceiver.dataReceived(self,recd)
		
	def stringReceived(self, line):
		self.logger.debug("Received message %s", repr(line))
		if line == "":
			return self.handle_KEEPALIVE()
		message_id = int(ord(line[0]))
		if message_id == 0:
			return self.handle_CHOKE()
		if message_id == 1:
			return self.handle_UNCHOKE()
		if message_id == 2:
			return self.handle_INTERESTED()
		if message_id == 3:
			return self.handle_NOT_INTERESTED()
		if message_id == 4:
			return self.handle_HAVE(line[1:])
		if message_id == 5:
			return self.handle_BITFIELD(line[1:])
		if message_id == 6:
			return self.handle_REQUEST(line[1:])
		if message_id == 7:
			return self.handle_PIECE(line[1:])
		if message_id == 8:
			return self.handle_CANCEL(line[1:])
		if message_id == 9:
			return self.handle_PORT()
		else:
			self.logger.info("Unsupported message %d received from peer %s", message_id, self.transport.getPeer())
			self.abortConnection()
			
	def handle_KEEPALIVE(self):
		pass
	
	def send_KEEPALIVE(self):
		self.sendString("")	
	
	def send_HANDSHAKE(self, info_hash):
		self.transport.write("".join(['\x13', 'BitTorrent protocol', '\x00'*8, info_hash, self.client.peer_id]))
	
	def handle_HANDSHAKE(self, instream):
		pstrlen = ord(instream[0])
		start = 1
		pstr = instream[start:pstrlen+start]
		start = start + pstrlen
		reserved = instream[start:start+8]
		start = start + 8
		info_hash = instream[start:start+20]
		start = start + 20
		peer_id = instream[start:start+20]
		self.logger.debug("Handshake from %s: pstr=%s reserved=%s info_hash=%s peer_id=%s",\
			self.transport.getPeer(),\
			pstr, \
			reserved.encode("hex"), \
			repr(info_hash), \
			repr(peer_id)\
		)
		self.info_hash = info_hash
		self.peer = self.client.add_peer(info_hash, self.transport.getPeer().host, self.transport.getPeer().port, peer_id, connection=self)
		self.send_HANDSHAKE(info_hash)
		self.state="ACTIVE"
	
	def handle_CHOKE(self):
		self.peer.choked = True
		
	def send_CHOKE(self):
		self.sendString('\x00')
	
	def handle_UNCHOKE(self):
		self.peer.choked = False
		
	def send_UNCHOKE(self):
		self.sendString('\x01')
		
	def handle_INTERESTED(self):
		self.peer.interested=True
	
	def send_INTERESTED(self):
		self.sendString('\x02')
	
	def handle_NOT_INTERESTED(self):
		self.peer.interested=False
	
	def send_NOT_INTERESTED(self):
		self.sendString('\x03')
	
	def send_HAVE(self, piece):
		self.sendString('\x04' + struct.pack('!I', piece))
	
	def handle_HAVE(self,line):
		index = struct.unpack('!I', line)
		self.peer.set_have(index)

	def handle_REQUEST(self,line):
		self.peer.add_request(*struct.unpack('!3I',line))
	
	def send_REQUEST(self,piece,begin,length):
		self.sendString('\x06' + struct.pack('!3I', piece,begin,length))
	
	def handle_BITFIELD(self, line):
		self.peer.set_bitfield(line)
	
	def send_BITFIELD(self, bits):
		self.sendString('\x05' + bits)
	
	def handle_PIECE(self,line):
		index,begin = struct.unpack('!II',line[:8])
		block = line[8:]
		self.logger.debug("Storing %d bytes at chunk %d offset %d",len(block), index,begin)
		self.client.store_piece(self.info_hash,index,begin,block)
		
	def send_PIECE(self, index, begin, block):
		self.sendString('\x07' + struct.pack('!II', index,begin) + block)
	

class PeerClientFactory(Factory):
	
	def __init__(self,client):
		self.client = client
	
	def buildProtocol(self, addr):
		return PeerConnection(self.client)
