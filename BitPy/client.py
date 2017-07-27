import random
import requests
import bencode
import logging

import math
import hashlib

import bisect

import os

import itertools

from twisted.internet import task,reactor

import protocol

class Download():
	logger = logging.getLogger(__name__)

	def __init__(self, torrent, filename=None, file=None):
		self.torrent = torrent
		self.peers = []
		self.pieces = set()
		self.piece_state = {}
		self.tracker_id = None
		self.connected_peers = []
		
		self.filename = 'torrent.dat'
		
		
		if self.torrent.info.filemode == 'single':
			self.filename = os.sep.join(self.torrent.info.files[0]['path'])
			
		if filename:
			self.filename = filename
		
		if file:
			self.file = file
			return
		
		if not os.path.exists(self.filename):
			self.logger.debug("Creating file %s", self.filename)
			open('file', 'w').close()
		
		self.file = open(self.filename, "r+b")

		if os.path.getsize(self.filename) != self.torrent.info.size:
			self.logger.info("Creating file %s as size(%d) is wrong (should be %d)",self.filename,os.path.getsize(self.filename),self.torrent.info.size)
			self.file.seek(self.torrent.info.size -1)
			self.file.write('\0')
			self.file.truncate()
			self.file.seek(0)
			
		else:
			self.check_progress()

	def check_progress(self):
		self.logger.info("Loading %d pieces from %s",self.torrent.info.num_pieces,self.filename)
		count = 0
		for piece in range(self.torrent.info.num_pieces):
			if self.verify_piece(piece):
				count += 1
		self.logger.info("Loaded %d completed pieces, progress is %f", count, self.progress)
			

	@property
	def bitfield(self):
		num_pieces = self.torrent.info.num_pieces

		bitfield = list('\x00' * int(math.ceil(num_pieces / 8.0)))

		#self.logger.debug("State is %s", repr(self.piece_state))

		for piece in self.pieces:
			#self.logger.debug("Have piece %d",piece)
			index = piece // 8
			bit   = 7 - (piece % 8)
			bitfield[index] = chr(ord(bitfield[index]) | (1 << bit))
			#self.logger.debug("index is %d, bit is %d, bitfield is %s", index,bit,bitfield)
		return bitfield
	
	@property
	def finished_pieces(self):
		return len(self.pieces)

	@property
	def progress(self):
		pieces = self.torrent.info.num_pieces
		return self.finished_pieces/float(pieces)

	def get_piece(self,index,start=0, length=None):
		self.seek_block_part(index,start)
		readsize = length if length else self.piece_size(index)
		return self.file.read(readsize)

	
	def verify_piece(self, index):
		piece = self.get_piece(index)
		sha1 = hashlib.sha1()
		sha1.update(piece)
		hash = sha1.digest()
		if hash == self.torrent.info.pieces[index]:
			self.pieces.add(index)
			self.logger.debug("Piece %d verified, progress is %f",index,self.progress)
			return True
		#self.logger.debug("Piece %d failed hash check",index)
		if index in self.piece_state:
			del self.piece_state[index]
		return False

	def have_piece(self, index):
		if index in self.pieces:
			return True
		
		
	def piece_progress(self, index):
		if self.have_piece(index):
			return 1
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
		if self.have_piece(index):
			return
			
		data_size = len(data)

		file_offset = index * self.torrent.info.piece_length + begin

		assert file_offset + len(data) <= self.torrent.info.size
		self.seek_block_part(index,begin)
		self.file.write(data)
		self.file.flush()

		state = self.piece_state.get(index, [])
		
		inserted = False
		
		insert_pos = -1
		
		
		for i in range(len(state)):
			(start, last) = state[i]
			if last == begin:
				state[i] = (start, begin+data_size)
				(start, last) = state[i]
				insert_pos = i
				inserted = True
				self.logger.debug("Growing piece %d to %d,%d"%(index,start,begin+data_size))
		if inserted:
			if insert_pos+1 < len(state):
				if begin + data_size == state[insert_pos+1][0]:
					state[insert_pos] = (state[insert_pos][0],state[insert_pos+1][1])
					del state[insert_pos+1]
		else:		
			state.append((begin, begin+data_size))
			state.sort()

		self.logger.debug("State is %s", state)

		self.piece_state[index] = state
		
		if self.piece_progress(index) == 1:
			self.verify_piece(index)




	def piece_size(self,index):
		if index < (self.torrent.info.num_pieces - 1):
			return self.torrent.info.piece_length
		else:
			return self.torrent.info.size - (self.torrent.info.num_pieces - 1)* self.torrent.info.piece_length 

	@property
	def missing_pieces(self):
		return [piece for piece in xrange(0,len(self.torrent.info.pieces)) if not self.have_piece(piece)]

class Peer():
	def __init__(self, host, port, peer_id=None, pieces=0):
		self.peer_id = peer_id
		self.host = host
		self.port = port
		self.bitfield = list('\x00' * int(math.ceil(pieces / 8.0)))
		self._choked = True
		self.interested = False
		self.requests = set()
		self.received = 0
		self.sent = 0
	
	def __hash__(self):
		return hash((self.host,self.port))
	
	def __eq__(self,other):
		return self.host == other.host and self.port == other.port
	
	@property
	def choked(self):
		return self._choked
	
	@choked.setter
	def choked(self,value):
		self._choked = value
		if self.choked:
			self.requests = set()

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


	def __init__(self, torrent, file=None):
		self.uploaded = 0
		self.downloaded = 0
		self.peers_wanted = 300
		self.peer_connection_max = 10
		self.peer_id = '-TR' + ''.join(chr(random.randint(0x61,0x7a)) for _ in range(17))
		self.key = ''.join(chr(random.randint(0x61,0x7a)) for _ in range(20))
		self.peers = []
		self.connected_peers = []
		self.torrent = torrent
		self.download = Download(torrent,file=file)
		self.port = 8123
		self.tracker_id = None
		self.requests = set()
		self.peer_start = 0
		self.disable_announce = False
		self.request_buffer_size=50
		self.live_requests = 0
		self.inprogress_requests = set()
		self.requested_parts = set()

	def check_peers(self):
		peers_to_get = self.peer_connection_max - len(self.connected_peers)
		self.logger.info("Trying to get %d peers", peers_to_get)
		for i in range(self.peer_start,min(len(self.peers),self.peer_start + peers_to_get)):
			self.connect_peer(self.peers[i])
		self.peer_start += peers_to_get
		if self.peer_start > len(self.peers):
			self.peer_start = 0

	def listen_for_connections(self):
		return reactor.listenTCP(self.port, protocol.PeerClientFactory(self))

	def connect_peer(self, peer):
		return reactor.connectTCP(peer.host, peer.port, protocol.PeerClientFactory(self))
	
	def disconnect_peer(self,peer):
		if peer in self.connected_peers:
			self.connected_peers.remove(peer)
			#self.check_peers()

	def handle_request(self,peer,request):
		piece,begin,length = request
		if self.download.have_piece(piece) and not peer.choked:
			peer.sent += length
			peer.connection.send_PIECE(piece,begin,self.download.get_piece(piece,begin,length))
			
	def handle_piece(self, peer, index, begin, data):
		"""
		When a peer finishes downloading a piece and checks that the hash matches, it announces that it has that piece to all of its peers.

		"""
		self.download.store_piece(index,begin,data)
		peer.received += len(data)
		if self.download.have_piece(index):
			self.notify_have(index)
		self.live_requests -= 1
		self.inprogress_requests.remove((index,begin))
		self.send_request()
	
	def notify_have(self,index):
		for peer in self.connected_peers:
			peer.connection.send_HAVE(index)

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

		can_send = [(idx,bits) for idx,bits in enumerate(have_need) if bits != 0]

		for idx,bits in can_send:
			offset = idx * 8
			for bit in range(0,8):
				if (1 << (7-bit)) & bits:
					yield offset + bit

	def start(self):
		if not self.disable_announce:
			self.logger.info("Announcing to tracker")
			tracker_call = task.LoopingCall(self.ping_tracker)
			tracker_call.start(300.0)
		
		peer_call = task.LoopingCall(self.check_peers)
		peer_call.start(60.0) 
		
		choke_peers_call = task.LoopingCall(self.choke_peers)
		choke_peers_call.start(10.0)
		
		
		task.LoopingCall(self.info).start(30)
		
		for request in range(10):
			self.send_request()
		
		

	
	def ping_tracker(self):
		announce = self.tracker_event()
		self.handle_tracker_response(announce)
		
	def info(self):
		"""
		Prints some information about the state of the client
		"""
		counts = {}
		for (peer,piece,part) in self.requests:
			counts[peer] = 0 if peer not in counts else counts[peer] + 1
		
		self.logger.info("Download %f%% (have %d pieces), %d connected clients, %d total peers, %d requests buffered, %d live requests, %d peers being requested, %r",
		self.download.progress * 100, self.download.finished_pieces,
		len(self.connected_peers),
		len(self.peers),
		len(self.requests),
		self.live_requests,
		len(counts.keys()),
		counts
		)
	
	def choke_peers(self):
		"""
		Decide which peers we want to send us something based on what
		we know of them so far
		"""
		for peer in self.connected_peers:
			peer.connection.send_UNCHOKE()
		
	def fill_request_buffer(self):
		"""
		Buffer a large number of requests to send.
		As soon as we receive responses we will use this list to request
		more data to saturate the connection.
		"""

		if len(self.requests) > self.request_buffer_size:
			return
		for peer in self.connected_peers:
			if peer.choked:
				continue
			pieces = self.get_pieces_to_request(peer)
			chunks_requested = 0
			for piece in pieces:
				for part in range(0,self.download.piece_size(piece),2**14):
					if not self.download.have_piece_range(piece,part,2**14):
						if not (piece,part) in self.requested_parts and \
							not (piece,part) in self.inprogress_requests:
							chunks_requested += 1
							self.requests.add((peer,piece,part))
							self.requested_parts.add((piece,part))
				if chunks_requested >= 10:
					break
	
	def send_request(self):
		"""
		Make a request from the request buffer.
		This function is re-entrant: a call to it starts a repeated
		chain of callbacks to the function, via the handle_piece
		method. Three things can happen:
		1. There are no requests to make
		2. The scheduled peer has disconnected
		3. The peer is connected and the piece hasn't already been asked for
		
		"""
		# What we need here is to have
		# several pieces per peer that we've asked for
		# so each peer has a buffer and a chain of requests
		# This method is responsible for keeping a live connection
		# to a peer full.
		
		# It does this by:
		# Asking for pieces to request as a list
		# taking the first element of the list
		# requesting it with a callback
		# When a piece is requested it is removed from the request queue
		# It sits on a waiting to hear back queue
		# After a timeout it goes back on the main queue
		# After a response it gets removed and doesn't go anywhere
		
		# Possible bugs:
		# When the queue is being filled, a request might have been removed
		# 
		self.fill_request_buffer()
		if self.requests:
			valid_request = False
			
			while not valid_request and self.requests:
				peer,piece,part = self.requests.pop()
				valid_request = not self.download.have_piece_range(piece,part,2**14)
			if peer.connection and valid_request:
				peer.connection.send_UNCHOKE()
				peer.connection.send_INTERESTED()
				self.logger.debug("Requesting piece %d:%d from %s",piece,part,peer)
				peer.connection.send_REQUEST(piece,part,2**14)
				self.inprogress_requests.add((piece,part))
				self.live_requests +=1 
				def timeout_request():
					if not self.download.have_piece_range(piece,part,2**14):
						self.logger.debug("Request for piece %d:%d from %s timed out",piece,part,peer)
						self.inprogress_requests.remove((piece,part))
						self.requested_parts.remove((piece,part))
						self.live_requests -= 1
						self.send_request()
				reactor.callLater(30, timeout_request)
				
			else:
				reactor.callLater(10,self.send_request)
		else:
			reactor.callLater(10,self.send_request)
		

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
