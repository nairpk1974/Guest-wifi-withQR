"""RADIUS Disconnect-Request (RFC 5176) sender used for immediate revocation / expiry enforcement.

FortiGate must have `set radius-coa enable` on the RADIUS server object and accept UDP/3799 from the
application server. Exact behaviour is verified per firmware during Phase 8 testing.
"""
import logging
import os

from pyrad import packet
from pyrad.client import Client, Timeout
from pyrad.dictionary import Dictionary

log = logging.getLogger(__name__)
_DICT = Dictionary(os.path.join(os.path.dirname(__file__), "radius_dictionary"))


def send_disconnect(host: str, port: int, secret: str, username: str, acct_session_id: str | None = None,
                    client_ip: str | None = None, timeout: int = 3, retries: int = 2) -> tuple[bool, str]:
    if not host or not secret:
        return False, "CoA host/secret not configured"
    client = Client(server=host, coaport=port, secret=secret.encode(), dict=_DICT)
    client.timeout = timeout
    client.retries = retries
    req = client.CreateCoAPacket(code=packet.DisconnectRequest)
    req["User-Name"] = username
    if acct_session_id:
        req["Acct-Session-Id"] = acct_session_id
    if client_ip:
        req["Framed-IP-Address"] = client_ip
    try:
        reply = client.SendPacket(req)
    except Timeout:
        return False, "timeout"
    except OSError as exc:
        return False, f"socket error: {exc}"[:120]
    if reply.code == packet.DisconnectACK:
        return True, "ack"
    cause = reply.get("Error-Cause", [""])[0] if "Error-Cause" in reply else ""
    return False, f"nak {cause}".strip()
