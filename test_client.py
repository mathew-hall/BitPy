from nose.tools import assert_equals
import BitPy.bencode

def test_bencode_string():
	assert_equals(BitPy.bencode.bencode_string("foo"), "3:foo")
	
def test_bencode_integer():
	assert_equals(BitPy.bencode.bencode_integer(50), "i50e")
	
def test_bencode_list():
	assert_equals(BitPy.bencode.bencode_list(['abc',5,['2'],[]]), "l43:abci5el11:2elee")
	
def test_bencode_dict():
	assert_equals(BitPy.bencode.bencode_dict({'abc':123,'def':{}}), 'd3:abci123e3:defdee')

def test_bendecode_string():
	assert_equals(BitPy.bencode.bendecode("3:foo"), "foo")
	
def test_bendecode_integer():
	assert_equals(BitPy.bencode.bendecode("i50e"), 50)

def test_bendecode_list():
	assert_equals(BitPy.bencode.bendecode("le"),[])
	assert_equals(BitPy.bencode.bendecode("li1ei2ei3ee"),[1,2,3])
	assert_equals(BitPy.bencode.bendecode("d3:abci3ee"),{'abc':3})