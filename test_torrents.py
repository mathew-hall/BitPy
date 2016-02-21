from nose.tools import assert_equals
from nose.tools import assert_true
import BitPy.torrents

def test_load_ubuntu():
	file = BitPy.torrents.load_torrent_file("ubuntu-15.10-desktop-amd64.iso.torrent")
	assert_equals(file.announce, "http://torrent.ubuntu.com:6969/announce")
	assert_equals(file.creation_date, 1445507299)
	assert_equals(file.info.filemode,'single')
	assert_equals(file.info.files,[{'path':['ubuntu-15.10-desktop-amd64.iso'], 'length':1178386432, 'md5sum':None}])