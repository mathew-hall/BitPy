import re

def bencode_string(value):
	return ":".join([str(len(value)),value])

def bencode_integer(number):
	return "i%de"%number
	
def bencode_list(values):
	items = len(values)
	if items == 0:
		return "le"
	return "l%d%se"%(items,"".join(map(bencode, values)))

def bencode_dict(values):
	encoded_values = ["".join((bencode(k), bencode(v))) for k,v in values.iteritems()]
	return "d%se"%"".join(encoded_values)
	
	
def bencode(value):
	if isinstance(value, str):
		return bencode_string(value)
	if isinstance(value, dict):
		return bencode_dict(value)
	if isinstance(value, list):
		return bencode_list(value)
	else:
		return bencode_integer(value)

def bendecode_string(value):
	(size,remainder) = value.split(':',1)
	string = remainder[0:int(size)]
	last = remainder[int(size):]
	return (string,last)

def bendecode_integer(string):
	skip_i = string[1:]
	digits = re.search('\d+',skip_i)
	number = int(skip_i[:digits.end()])
	remainder = skip_i[digits.end():]
	return (number,remainder[1:])

def bendecode_list(string):
	skip_l = string[1:]
	result = []
	rest = skip_l
	while rest[0] != 'e':
		(item,rest) = bendecode_chunk(rest)
		result.append(item)
	return (result,rest[1:])

def bendecode_dict(string):
	skip_d = string[1:]
	result = {}
	rest = skip_d
	while rest[0] != 'e':
		(key, rest) = bendecode_chunk(rest)
		(val, rest) = bendecode_chunk(rest)
		result[key] = val
	return (result,rest[1:])

def bendecode_chunk(string):
	first = string[0]
	if first.isdigit():
		return bendecode_string(string)
	if first == 'i':
		return bendecode_integer(string)
	if first == 'l':
		return bendecode_list(string)
	if first == 'd':
		return bendecode_dict(string)
	raise Exception('Unsupported type %s %s'%(first,repr(string)))

def bendecode(string):
	return bendecode_chunk(string)[0]