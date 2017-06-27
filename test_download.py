import mock

import BitPy.client
import BitPy.torrents


from nose.tools import assert_equals
from nose.tools import assert_true
from nose.tools import assert_false

import tempfile

def test_download_status():
	file = BitPy.torrents.load_torrent_file("ubuntu-15.10-desktop-amd64.iso.torrent")
	download = BitPy.client.Download(file, file=tempfile.SpooledTemporaryFile())
	download.file=open("/tmp/test.dat",'wb')
	download.torrent.info.pieces = ['3495ff69d34671d1e15b33a63c1379fdedd3a32a']
	download.torrent.info.piece_length=10
	
	download.store_piece(0,0,'a')	
	assert_equals(download.piece_state[0],[(0,1)])
	
	download.store_piece(0,2,'a')
	assert_equals(download.piece_state[0],[(0,1),(2,3)])
	
	download.store_piece(0,1,'a')
	
	assert_equals(download.piece_state[0],[(0,3)])
	