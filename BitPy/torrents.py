import bencode

class Info:
	piece_length = None
	pieces = None
	private = 0
	name = None
	files = []
	filemode = None
	def __init__(self, info_struct):

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
			
		
	def add_file(self, path, length, md5sum=None):
		self.files.append({'path':path,'length':length,'md5sum':md5sum})
	
	
class TorrentFile:
	info = None
	announce = None
	announce_list = None
	creation_date = None
	comment = None
	created_by = None
	encoding = None
	
	def __init__(self, torrent_file_contents={}):
			for k,v in torrent_file_contents.items():
				if k != 'info':
					setattr(self,k.replace('-','_').replace(" ",'_'),v)
				else:
					self.info = Info(v)
	
	
	
	def __repr__(self):
		return repr({"info":self.info, "announce":self.announce, "announce-list":self.announce_list, "creation date": self.creation_date, "comment":self.comment, "created by": self.created_by, "encoding": self.encoding})

def load_torrent_file(path):
	with open(path) as torrentfile:
		contents = torrentfile.read()
		result = bencode.bendecode(contents)
		return TorrentFile(result)