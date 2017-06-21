import random
import requests
import bencode
import logging

import math
import hashlib


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
		self.file = open("torrent.dat", "wb")

		self.file.seek(self.torrent.info.size)
		self.file.write('\0')
		self.file.seek(0)


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

	@property
	def progress(self):
		pieces = len(self.torrent.info.pieces)
		return len(self.pieces)/float(pieces)

	def get_piece(self,index,start=0, length=None):
		if not self.have_piece(index):
			return None
		self.seek_block_part(index,start)
		readsize = length if length else self.piece_size(index)
		return self.file.read(readsize)


	def have_piece(self, index):
		if self.piece_progress(index) != 1: return False
		piece = self.get_piece(index)
		sha1 = hashlib.sha1()
		sha1.update(piece)
		return sha1.digest() == self.torrent.info.pieces[index]

	def piece_progress(self, index):
		piece_size = self.piece_size(index)
		if index not in self.piece_state:
			return 0

		current_end_byte = 0
		missing = 0
		for (start,next_byte) in self.piece_state[index]:
			missing = missing + start - current_end_byte
			current_end_byte = next_byte

		missing = missing + piece_size - current_end_byte

		return (piece_size - missing) / float(piece_size)

	def have_piece_range(self,index,start,length):
		if index not in self.piece_state:
			return False
		if length <= 0:
			return True

		next = 0

		for (s,n) in self.piece_state[index]:
			if s < next:
				continue
			# Start is somewhere in this block,
			# so we can just advance it to the next point,
			# reducing length by the amount we skip
			if start >= s and start <= n:
				skip = n - start
				start += skip
				length -= skip
			if length <= 0:
				return True
			next = n

	def seek_block_part(self,piece,offset=0):
		self.file.seek(piece * self.torrent.info.piece_length + offset)
		#return mmap.mmap(self.file, self.piece_size(piece), offset=piece * self.torrent.info.piece_length)

	def store_piece(self, index, begin, data):

		data_size = len(data)

		file_offset = index * self.torrent.info.piece_length + begin

		assert file_offset + len(data) <= self.torrent.info.size
		self.seek_block_part(index,begin)
		self.file.write(data)
		self.file.flush()

		state = self.piece_state.get(index, [])
		state.append((begin, begin+data_size))
		state.sort()

		self.logger.debug("State is %s", state)

		self.piece_state[index] = state



	def piece_size(self,index):
		if index < (self.torrent.info.num_pieces - 1):
			return self.torrent.info.piece_length
		else:
			return self.torrent.info.size - self.torrent.info.num_pieces * (self.torrent.info.piece_length - 1)

	@property
	def missing_pieces(self):
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
		#'bitfield': self.bitfield
		return repr({'peer id': self.peer_id, 'host':self.host, 'port':self.port, 'choked':self.choked, 'interested': self.interested})

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
		for i in range(0,min(len(self.peers),self.peers_wanted - len(self.connected_peers))):
			self.connect_peer(self.peers[i])

	def listen_for_connections(self):
		return reactor.listenTCP(self.port, protocol.PeerClientFactory(self))

	def connect_peer(self, peer):
		return reactor.connectTCP(peer.host, peer.port, protocol.PeerClientFactory(self))

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

	def start(self):
		self.logger.info("Announcing to tracker")
		announce = self.tracker_event()
		self.handle_tracker_response(announce)
		
		tick_call = task.LoopingCall(self.tick)
		tick_call.start(10.0)
		

	def tick(self):
		"""
		Decide what to do when the Twisted event loop gives us time.
		"""
		if len(self.connected_peers) < self.peers_wanted:
			self.logger.info("Connecting to some peers")
			self.check_peers()
			
		# First see if we can send anything requested:
		for peer in self.connected_peers:
			for piece in peer.requests:
				idx, begin, length = piece
				if self.download.have_piece(idx):
					self.logger.debug("Sending piece %s to peer %s"%(piece, peer))
					peer.connection.send_PIECE(idx,begin, self.download.get_piece(idx,begin,length))
				
		# Do we have any pieces thy don't?
		for peer in self.connected_peers:
			#Note: we should be smarter about this.
			if not peer.choked:
				pieces_interested = self.get_pieces_to_send(peer)
				for piece in itertools.islice(pieces_interested,1):
					self.logger.debug("Sending piece %s to peer %s"%(piece, peer))
					peer.connection.send_PIECE(piece, 0, self.download.get_piece(piece))

		requests = {}
		# Do they have any pieces we don't?
		for peer in self.connected_peers:
			if peer.choked:
				continue
			pieces = self.get_pieces_to_request(peer)
			for piece in itertools.islice(pieces, 1):
				peer.connection.send_UNCHOKE()
				self.logger.debug("Requesting piece %s from peer %s"%(piece,peer))
				for part in range(0,self.download.piece_size(piece),2**14):
					if not self.download.have_piece_range(piece,part,2**14):
						requests[(piece,part)] = peer
		for (data,peer) in requests.iteritems():
			piece,part = data
			peer.connection.send_REQUEST(piece, part, 2**14)


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
		if peer_id is not None and peer.peer_id is not None and (peer.peer_id != peer_id):
			self.logger.warn("Peer %s has changed IDs to %s",repr(peer), repr(peer_id))
		elif peer_id is not None and peer.peer_id is None:
			peer.peer_id = peer_id

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
