import random
import requests
import bencode
import logging
import struct
import math
import hashlib

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
	
	@property
	def bitfield(self):
		num_pieces = len(self.torrent.info.pieces)
		
		bitfield = list('\x00' * int(math.ceil(num_pieces / 8.0)))
		
		self.logger.debug("State is %s", repr(self.piece_state))
		
		for piece,state in self.piece_state.iteritems():
			if self.piece_progress(piece) == 1:
				self.logger.debug("Have piece %d",piece)
				index = piece // 8
				bit   = 7 - (piece % 8)
				bitfield[index] = chr(ord(bitfield[index]) | (1 << bit))
				self.logger.debug("index is %d, bit is %d, bitfield is %s", index,bit,bitfield)
		return bitfield
		
	def get_progress(self):
		pieces = len(self.torrent.info.pieces)
		return len(self.pieces)/float(pieces)
	
	def get_piece(self,index,start=None, length=None):
		return "".join(self.pieces[index])
		
	def have_piece(self, index):
		if self.piece_progress(index) != 1: return False
		piece = self.get_piece(index)
		sha1 = hashlib.sha1()
		sha1.update(piece)
		return sha1.digest() == self.torrent.info.pieces[index]
		
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
		
	def get_missing_pieces(self):
		return [piece for piece in xrange(0,len(self.torrent.info.pieces)) if not self.have_piece(piece)]

class Peer():
	def __init__(self, host, port, peer_id=None, pieces=0):
		self.peer_id = peer_id
		self.host = host
		self.port = port
		self.bitfield = list('\x00' * int(math.ceil(pieces / 8.0)))
		self.choked = True
		self.interested = False
		self.requests = []
	
	def set_have(self, piece):
		index = piece // 8
		bit   = 7 - (piece % 8)
		self.bitfield[index] = chr(ord(self.bitfield[index]) | (1 << bit))
		
	def set_bitfield(self, bitfield):
		self.bitfield = list(bitfield)
	
	def add_request(self, index, begin, length):
		self.requests.append((index,begin,length))
	
	def __repr__(self):
		return repr({'peer id': self.peer_id, 'host':self.host, 'port':self.port, 'bitfield': self.bitfield, 'choked':self.choked, 'interested': self.interested})

class Client():

	logger = logging.getLogger('client')
	
	
	def __init__(self, torrent):
		#TODO: add scrape to reactor
		self.uploaded = 0
		self.downloaded = 0
		self.peers_wanted = 20
		self.peer_id = ''.join(chr(random.randint(0,255)) for _ in range(20))
		self.key = ''.join(chr(random.randint(0,255)) for _ in range(20))
		self.peers = []
		self.connected_peers = []
		self.torrent = torrent
		self.download = Download(torrent)
		self.port = 8123
		self.tracker_id = None

	def check_peers(self):
		for i in range(0,self.peers_wanted - len(self.connected_peers)):
			self.connect_peer(self.peers[i])
	
	def listen_for_connections(self):
		return reactor.listenTCP(self.port, PeerClientFactory(self))
	
	def connect_peer(self, peer):
		return reactor.connectTCP(peer.host, peer.port, PeerClientFactory(self))
		
	def handle_request(self,peer,request):
		piece,begin,length = request
		if self.download.have_piece(piece):
			peer.connection.send_PIECE(piece,begin,self.download.get_piece(piece,begin,length))
			
	def get_pieces_to_request(self, peer):
		my_pieces = self.download.bitfield
		peer_bitfield = peer.bitfield
		need_have = [~ord(mine) & ord(theirs) for (mine,theirs) in zip(my_pieces, peer_bitfield)]	
		can_request = [(idx,bits) for idx,bits in enumerate(need_have) if bits != 0]
		for idx, bits in can_request:
			offset = idx * 8
			for bit in range(0,8):
				if (1 << (7-bit)) & bits:
					yield offset + bit
					
	def get_pieces_to_send(self, peer):
		my_pieces = self.download.bitfield
		peer_bitfield = peer.bitfield
		have_need = [ord(mine) & (~ord(theirs)) for (mine,theirs) in zip(my_pieces, peer_bitfield)]
		self.logger.debug("Computed difference between bitfields as %s", str(have_need))
		can_send = [(idx,bits) for idx,bits in enumerate(have_need) if bits != 0]
		self.logger.debug("Can send %s", can_send)
		for idx,bits in can_send:
			offset = idx * 8
			self.logger.debug("Difference for bits: %s", str(bits))
			for bit in range(0,8):
				self.logger.debug("For bit %s, and field %s, result is %s %s", bit, bits, (1 << (7-bit)) & bits,  (1 << (7-bit)))
				if (1 << (7-bit)) & bits:
					yield offset + bit
	
	def tick(self):
		"""
		Decide what to do when the Twisted event loop gives us time.
		"""
		# Have we been asked for any pieces? Send those first
		for peer in self.connected_peers:
			for request in peer.requests:
				self.handle_request(request)
		# Do we have any pieces thy don't?
		for peer in self.connected_peers:
			#Note: we should be smarter about this.
			piece = list(get_pieces_to_send(peer))[0]
			peer.connection.send_PIECE(piece, 0, self.download.get_piece(piece,begin))
		# Do they have any pieces we don't?
		for peer in self.connected_peers:
			piece = list(get_pieces_to_request(peer))[0]
			peer.connection.send_REQUEST(piece, 0, self.torrent.info.piece_length)
			
		
	def get_needed(self):
		return 0
	
	def handle_tracker_response(self,message):
		self.logger.info("Tracker state update for %s",str(message))
		self.tracker_id = message.get('tracker id',None)
		peerlist = message.get('peers',"")
		for start in xrange(0,len(peerlist),6):
			peer = [str(ord(c)) for c in list(peerlist[start:start+6])]
			host = ".".join(peer[0:4])
			port = int(peer[4]) << 8 | int(peer[5])
			self.add_peer(host,port)
		self.logger.info("Torrent state is now %s", str(self.torrent))
	
	def add_peer(self, host, port, peer_id=None, connection=None):
		peer = self.get_peer(host=host, port=port, peer_id=peer_id)
		if peer is None:
			peer = Peer(host,port,peer_id,len(self.torrent.info.pieces))
			self.peers.append(peer)
		if connection:
			peer.connection = connection
			self.connected_peers.append(peer)
		if peer_id is not None and (peer.peer_id != peer_id):
			self.logger.warn("Peer %s has changed IDs to %s",repr(peer), repr(peer_id))
			
		return peer
		
	def get_peer(self, peer_id=None, host=None, port=None):
		for peer in self.peers:
			if (peer_id is not None and peer.peer_id == peer_id) or (peer.host == host and peer.port == port):
				return peer
		return None

	def tracker_event(self, event=""):
		tracker = self.torrent.announce
		params={\
			'info_hash':self.torrent.info_hash, \
			'peer_id':self.peer_id, \
			'port': self.port, \
			'uploaded': self.uploaded, \
			'downloaded': self.downloaded, \
			'compact': 1, \
			'numwant': self.peers_wanted, \
			'key': self.key.encode("hex") \
		}
		
		params['left'] = self.get_needed()
		
		if self.tracker_id:
			params['trackerid'] = self.tracker_id
		if event:
			params['event'] = event
		
		self.logger.info("Pinging tracker at %s with params %s", tracker,params)
		response = requests.get(tracker,params=params)
		if response.status_code != 200:
			return None
		
		result = bencode.bendecode(response.text)
		return result
		




messages = {
	0:'CHOKE',
	1:'UNCHOKE',
	2:'INTERESTED',
	3:'NOT_INTERESTED',
	4:'HAVE',
	5:'BITFIELD',
	6:'REQUEST',
	7:'PIECE',
	8:'CANCEL',
	9:'PORT'
}


class PeerConnection(Int32StringReceiver):
	logger = logging.getLogger('tcpserver')
	def __init__(self, client):
		self.state = "HANDSHAKE"
		self.preamble_size = 0
		self.client = client
		self.peer = None
		
	def connectionMade(self):
		self.send_HANDSHAKE()
	
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
		if message_id not in messages:
			self.logger.info("Unsupported message %d received from peer %s", message_id, self.transport.getPeer())
		handler = getattr(self, "handle_%s"%messages[message_id])
		return handler(line[1:])
		
			
			
	def handle_KEEPALIVE(self):
		pass
	
	def send_KEEPALIVE(self):
		self.sendString("")	
	
	def send_HANDSHAKE(self):
		self.transport.write("".join(['\x13', 'BitTorrent protocol', '\x00'*8, self.client.torrent.info_hash, self.client.peer_id]))
	
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
		self.peer = self.client.add_peer(self.transport.getPeer().host, self.transport.getPeer().port, peer_id, connection=self)
		if self.client.download.get_progress() != 0:
			self.send_BITFIELD(self.client.download.bitfield)
		
		self.state="ACTIVE"
	
	def handle_CHOKE(self,line):
		self.peer.choked = True
		
	def send_CHOKE(self):
		self.sendString('\x00')
	
	def handle_UNCHOKE(self,line):
		self.peer.choked = False
		
	def send_UNCHOKE(self):
		self.sendString('\x01')
		
	def handle_INTERESTED(self,line):
		self.peer.interested=True
	
	def send_INTERESTED(self):
		self.sendString('\x02')
	
	def handle_NOT_INTERESTED(self,line):
		self.peer.interested=False
	
	def send_NOT_INTERESTED(self):
		self.sendString('\x03')
	
	def send_HAVE(self, piece):
		self.sendString('\x04' + struct.pack('!I', piece))
	
	def handle_HAVE(self,line):
		self.logger.debug("Got HAVE message %s", repr(line))
		index, = struct.unpack('!I', line)
		self.peer.set_have(index)

	def handle_REQUEST(self,line):
		self.peer.add_request(*struct.unpack('!3I',line))
	
	def send_REQUEST(self,piece,begin,length):
		self.sendString('\x06' + struct.pack('!3I', piece,begin,length))
	
	def handle_BITFIELD(self, line):
		self.peer.set_bitfield(line)
	
	def send_BITFIELD(self, bits):
		self.sendString('\x05' + self.download.bitfield)
	
	def handle_PIECE(self,line):
		index,begin = struct.unpack('!II',line[:8])
		block = line[8:]
		self.logger.debug("Storing %d bytes at chunk %d offset %d",len(block), index,begin)
		self.client.download.store_piece(index,begin,block)
		
	def send_PIECE(self, index, begin, block):
		self.sendString('\x07' + struct.pack('!II', index,begin) + block)
	

class PeerClientFactory(Factory):
	#TODO: notify client on disconnect
	
	def __init__(self,client):
		self.client = client
		
	def startedConnecting(self, connector):
			print 'Started to connect.'
	
	def clientConnectionLost(self,reason,_):
		pass
	
	def clientConnectionFailed(self,reason,_):
		pass
	
	def buildProtocol(self, addr):
		return PeerConnection(self.client)

