"""Fake FortiGate CoA/Disconnect listener for lab testing: ACKs every Disconnect-Request and logs it.
Usage: python tests/fake_coa_server.py <secret> [port] [logfile]"""
import os
import socket
import sys

from pyrad import packet
from pyrad.dictionary import Dictionary

secret = sys.argv[1].encode()
port = int(sys.argv[2]) if len(sys.argv) > 2 else 3799
logf = sys.argv[3] if len(sys.argv) > 3 else "/tmp/coa.log"
d = Dictionary(os.path.join(os.path.dirname(__file__), "..", "app", "radius_dictionary"))
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", port))
while True:
    data, addr = s.recvfrom(4096)
    req = packet.CoAPacket(packet=data, secret=secret, dict=d)
    attrs = {k: req[k] for k in req.keys()}
    with open(logf, "a") as f:
        f.write(f"{req.code} {attrs}\n")
    reply = req.CreateReply()
    reply.code = packet.DisconnectACK
    s.sendto(reply.ReplyPacket(), addr)
