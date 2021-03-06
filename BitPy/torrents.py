import bencode
import hashlib

class Info:

	def __init__(self, info_struct):
		self.piece_length = None
		self.files = []
		self.private = info_struct.get('private',0)
		self.piece_length = info_struct['piece length']
		def chunk_values(str):
			for start in xrange(0,len(str),20):
				yield(str[start:start+20])
		self.pieces = list(chunk_values(info_struct['pieces']))
		self.name = info_struct['name']
		if 'length' in info_struct:
			self.filemode = 'single'
			self.add_file([info_struct['name']], info_struct['length'],info_struct.get('md5sum',None))
		else:
			self.filemode = 'multiple'
			for filestruct in info_struct['files']:
				self.add_file(filestruct.path, filestruct.length, filestruct.get('md5sum',None))

	@property
	def num_pieces(self):
		return len(self.pieces)

	@property
	def size(self):
		return sum([f['length'] for f in self.files])


	def add_file(self, path, length, md5sum=None):
		self.files.append({'path':path,'length':length,'md5sum':md5sum})
	
	
class TorrentFile:
	"""
	A Torrent file contains the metadata we need to ask peers for file pieces.
	It contains, at least, an info and announce value; the info includes file metadata
	(including SHA1 hashes of the pieces) and the announce value specifies the tracker(s)
	that coordinate the swarm.
	"""

	
	def __init__(self, torrent_file_contents={}):
		self.info = None
		self.announce = None
		self.announce_list = None
		self.creation_date = None
		self.comment = None
		self.created_by = None
		self.encoding = None
		for k,v in torrent_file_contents.items():
			if k != 'info':
				setattr(self,k.replace('-','_').replace(" ",'_'),v)
			else:
				self.info = Info(v)
		
		sha1 = hashlib.sha1()
		sha1.update(bencode.bencode(torrent_file_contents['info']))
		self.info_hash = sha1.digest()
		
	def __repr__(self):
		return repr({"info":self.info, "announce":self.announce, "announce-list":self.announce_list, "creation date": self.creation_date, "comment":self.comment, "created by": self.created_by, "encoding": self.encoding, 'info hash': self.info_hash})

def load_torrent_file(path):
	with open(path) as torrentfile:
		contents = torrentfile.read()
		result = bencode.bendecode(contents)
		return TorrentFile(result)