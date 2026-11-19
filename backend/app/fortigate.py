"""Read-only FortiGate REST API lookups (device MAC / hostname for a guest IP).

Uses a dedicated REST API admin ("api-user") with a read-only profile, trusted only from the Docker-vm.
The token lives in .env (FGT_API_TOKEN_BLR / _HYD), never in the database.
FortiGates use self-signed certificates on their management interface, so TLS verification is off for
this internal call; the request only carries the read-only token and only goes to the configured IP.
"""
import json
import logging
import ssl
import time
import urllib.error
import urllib.request

from .config import get_settings
from .models import Location

log = logging.getLogger(__name__)
_CACHE: dict[int, tuple[float, list[dict]]] = {}
CACHE_SECONDS = 10
TIMEOUT = 4


def _norm_mac(v: str | None) -> str | None:
    if not v:
        return None
    h = "".join(c for c in v.lower() if c in "0123456789abcdef")
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)) if len(h) == 12 else None


def _get(loc: Location, path: str) -> dict:
    token = get_settings().api_token_for(loc.code)
    if not loc.api_url or not token:
        raise RuntimeError("API URL or token not configured")
    url = loc.api_url.rstrip("/") + path
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    # Direct connection only: never send the token through an HTTP proxy from the environment.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from FortiGate") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"cannot reach FortiGate API: {getattr(e, 'reason', e)}") from None
    except ValueError:
        raise RuntimeError("FortiGate returned invalid JSON") from None


def devices(loc: Location) -> list[dict]:
    """[{ip, mac, hostname, os, vendor}] from the device inventory, plus the ARP table as a fallback."""
    now = time.monotonic()
    hit = _CACHE.get(loc.id)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    out: dict[str, dict] = {}
    errors = []
    try:
        for d in _get(loc, "/api/v2/monitor/user/device/query").get("results", []) or []:
            ip = d.get("ipv4_address")
            if not ip:
                continue
            os_name = " ".join(x for x in (d.get("os_name"), d.get("os_version")) if x)
            vendor = " ".join(x for x in (d.get("hardware_vendor"), d.get("hardware_version")) if x)
            out[ip] = {"ip": ip, "mac": _norm_mac(d.get("mac")), "hostname": d.get("hostname") or None,
                       "os": os_name or None, "vendor": vendor or None}
    except RuntimeError as e:
        errors.append(f"device inventory: {e}")
    try:
        for a in _get(loc, "/api/v2/monitor/system/arp").get("results", []) or []:
            ip, mac = a.get("ip"), _norm_mac(a.get("mac"))
            if ip and mac:
                cur = out.setdefault(ip, {"ip": ip, "mac": None, "hostname": None, "os": None, "vendor": None})
                cur["mac"] = cur["mac"] or mac
    except RuntimeError as e:
        errors.append(f"ARP: {e}")
    if errors and not out:
        raise RuntimeError("; ".join(errors))
    result = list(out.values())
    _CACHE[loc.id] = (now, result)
    return result


def lookup(loc: Location, ip: str | None) -> dict | None:
    if not ip:
        return None
    for d in devices(loc):
        if d["ip"] == ip:
            return d
    return None


def configured(loc: Location) -> bool:
    return bool(loc.api_url and get_settings().api_token_for(loc.code))
