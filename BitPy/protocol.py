from twisted.protocols.basic import Int32StringReceiver
from twisted.internet.protocol import Factory
import logging
import struct

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
	
	def connectionLost(self,reason):
		if self.peer:
			self.logger.debug("Lost connection from %s",self.peer)
			self.client.disconnect_peer(self.peer)
			self.peer.connection = None
			
	def disconnect(self):
		self.transport.loseConnection()

	def dataReceived(self, recd):
		if self.state == "HANDSHAKE":
			self.recvd = self.recvd + recd
			#self.logger.debug("Received data in state %s: %s", self.state, repr(self.recvd))
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
		#self.logger.debug("Received message %s", repr(line))
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
		self.peer.choked = True
		if self.client.download.progress != 0:
			self.send_BITFIELD(self.client.download.bitfield)

		self.state="ACTIVE"

	def handle_CHOKE(self,line):
		self.peer.choked = True

	def send_CHOKE(self):
		self.sendString('\x00')

	def handle_UNCHOKE(self,line):
		self.logger.debug("Peer %s is unchoked"%self.peer)
		self.peer.choked = False

	def send_UNCHOKE(self):
		self.sendString('\x01')

	def handle_INTERESTED(self,line):
		self.peer.interested=True

	def send_INTERESTED(self):
		self.logger.debug("Sending Interested to Peer %s"%self.peer)
		self.sendString('\x02')

	def handle_NOT_INTERESTED(self,line):
		self.peer.interested=False

	def send_NOT_INTERESTED(self):
		self.sendString('\x03')

	def send_HAVE(self, piece):
		self.sendString('\x04' + struct.pack('!I', piece))

	def handle_HAVE(self,line):
		self.logger.debug("Got HAVE message from peer %s", self.peer)
		index, = struct.unpack('!I', line)
		self.peer.set_have(index)

	def handle_REQUEST(self,line):
		self.peer.add_request(*struct.unpack('!3I',line))

	def send_REQUEST(self,piece,begin,length):
		self.sendString('\x06' + struct.pack('!3I', piece,begin,length))

	def handle_BITFIELD(self, line):
		self.peer.set_bitfield(line)

	def send_BITFIELD(self, bits):
		self.sendString('\x05' + struct.pack('!%uc'%len(bits),*bits))

	def handle_PIECE(self,line):
		index,begin = struct.unpack('!II',line[:8])
		block = line[8:]
		self.client.handle_piece(self.peer,index,begin,block)

	def send_PIECE(self, index, begin, block):
		self.sendString('\x07' + struct.pack('!II', index,begin) + block)

	def handle_CANCEL(self, index, begin, length):
		pass

class PeerClientFactory(Factory):
	#TODO: notify client on disconnect
	logger = logging.getLogger('tcpserver')
	def __init__(self,client):
		self.client = client

	def startedConnecting(self, connector):
		#self.logger.info('Started to connect: %s'%repr(connector))
		pass

	def clientConnectionLost(self,reason,_):
		pass

	def clientConnectionFailed(self,reason,_):
		pass

	def buildProtocol(self, addr):
		return PeerConnection(self.client)
