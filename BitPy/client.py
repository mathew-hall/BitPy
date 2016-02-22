import random
import SocketServer
import requests
import bencode
import logging
import StringIO
import struct

from twisted.internet.protocol import Factory
from twisted.protocols.basic import Int32StringReceiver
from twisted.internet import reactor


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
		self.torrents[torrent.info_hash] = {\
			'peers': [], \
			'tracker id': None, \
			'pieces': {}, 
			'choked_peers': set()\
		}
	
	def get_needed(self,torrent):
		return 0
	
	def handle_tracker_response(self,info_hash,message):
		self.logger.info("Tracker state update for %s",str(message))
		self.torrents[info_hash]['tracker id'] = message.get('tracker id',None)
		peerlist = message.get('peers',"")
		for start in xrange(0,len(peerlist),6):
			peer = [str(ord(c)) for c in list(peerlist[start:start+6])]
			host = ".".join(peer[0:4])
			port = int(peer[4]) << 8 | int(peer[5])
			self.torrents[info_hash]['peers'].append({'host':host, 'port':port})
		self.logger.info("Torrent state is now %s", str(self.torrents[info_hash]))
		
	def store_piece(self,info_hash,index,begin,data):
		index_entry = self.torrents[info_hash]['pieces'].get(index,{})
		index_entry[begin] = data
		self.torrents[info_hash]['pieces'][index] = index_entry
	
	def choke_peer(self, info_hash, peer):
		self.torrents[info_hash]['choked_peers'].add(peer)
	
	def unchoke_peer(self, info_hash, peer):
		try:
			self.torrents[info_hash]['choked_peers'].remove(peer)
		except KeyError:
			pass

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
		




class Peer(Int32StringReceiver):
	logger = logging.getLogger('tcpserver')
	def __init__(self, client):
		self.state = "HANDSHAKE"
		self.preamble_size = 0
		self.client = client
	
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
		self.peer_id = peer_id
		self.state="ACTIVE"
	
	def handle_CHOKE(self):
		self.client.choke_peer(self.info_hash,self.peer_id)
	
	def handle_UNCHOKE(self):
		self.client.unchoke_peer(self.info_hash,self.peer_id)
	
	def handle_PIECE(self,line):
		index,begin = struct.unpack('!II',line[:8])
		block = line[8:]
		self.logger.debug("Storing %d bytes at chunk %d offset %d",len(block), index,begin)
		self.client.store_piece(self.info_hash,index,begin,block)


class PeerClientFactory(Factory):
	
	def __init__(self,client):
		self.client = client
	
	def buildProtocol(self, addr):
		return Peer(self.client)

