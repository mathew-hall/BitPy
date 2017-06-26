import BitPy.client
import BitPy.torrents

import sys

from twisted.internet.protocol import Factory, Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet import defer,reactor
import logging

from optparse import OptionParser

parser = OptionParser()
parser.add_option("-f", "--file", dest="filename",
					help="torrent filename", action="store", metavar="TORRENTFILE")
parser.add_option("-v", "--verify",
					dest="verify", default=False,
					action="store_true",
					help="verify download then exit")

(options, args) = parser.parse_args()

if not options.filename:
	parser.print_help()
	sys.exit(-1)

logging.basicConfig(level=logging.INFO)

logging.getLogger(__name__).info("Loading file %s", options.filename)

file = BitPy.torrents.load_torrent_file(options.filename)

client = BitPy.client.Client(file)

if not options.verify:
	logging.getLogger(__name__).info("Starting download of %s", options.filename)
	client.start()
	client.listen_for_connections()

	reactor.run()
