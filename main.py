import BitPy.client
import BitPy.torrents

from twisted.internet.protocol import Factory, Protocol
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet import defer,reactor
import logging

logging.basicConfig(level=logging.DEBUG)

file = BitPy.torrents.load_torrent_file("ubuntu-15.10-desktop-amd64.iso.torrent")
client = BitPy.client.Client(file)

client.start()
client.listen_for_connections()

reactor.run()