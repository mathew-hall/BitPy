from nose.tools import assert_equals
from nose.tools import assert_true
from nose.tools import raises
import BitPy.bencode

def test_bencode_string():
	assert_equals(BitPy.bencode.bencode("foo"), "3:foo")
	
def test_bencode_integer():
	assert_equals(BitPy.bencode.bencode(50), "i50e")
	
def test_bencode_list():
	assert_equals(BitPy.bencode.bencode(['abc',5,['2'],[]]), "l43:abci5el11:2elee")
	
def test_bencode_dict():
	assert_equals(BitPy.bencode.bencode({'abc':123,'def':{}}), 'd3:abci123e3:defdee')

def test_bendecode_string():
	assert_equals(BitPy.bencode.bendecode("3:foo"), "foo")
	
def test_bendecode_integer():
	assert_equals(BitPy.bencode.bendecode("i50e"), 50)

def test_bendecode_list():
	assert_equals(BitPy.bencode.bendecode("le"),[])
	assert_equals(BitPy.bencode.bendecode("li1ei2ei3ee"),[1,2,3])
	assert_equals(BitPy.bencode.bendecode("d3:abci3ee"),{'abc':3})

def test_bendecode_list_of_lists():
	assert_equals(BitPy.bencode.bendecode("lli1eee"),[[1]])

def test_bendecode_torrent_fragment():
	fragment = "d8:announce39:http://torrent.ubuntu.com:6969/announce13:announce-listll39:http://torrent.ubuntu.com:6969/announceel44:http://ipv6.torrent.ubuntu.com:6969/announceee7:comment29:Ubuntu CD releases.ubuntu.com13:creation datei1445507299ee"
	result = BitPy.bencode.bendecode(fragment)
	assert_true("announce" in result)
	
def test_bendecode_torrent():
	with open("ubuntu-15.10-desktop-amd64.iso.torrent") as torrentfile:
		contents = torrentfile.read()
		result = BitPy.bencode.bendecode(contents)
		assert_true("announce" in result) 
		assert_true("info" in result)
		
@raises(Exception)
def test_bendecode_invalid():
	BitPy.bencode.bendecode("Xinvalid")
	