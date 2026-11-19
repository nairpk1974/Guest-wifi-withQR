"""Best-effort device description from a browser User-Agent (no external dependency).

Browsers only reveal what they choose to: Android Chrome often hides the model ("Android 10; K"), iPhones
never say which model, and no browser exposes the device's hostname. The result is a hint for reception,
not an identity.
"""
import re

_ANDROID = re.compile(r"Android\s*([\d.]+)?;\s*([^;)]*)")
_IOS = re.compile(r"(iPhone|iPad|iPod).*?OS ([\d_]+)")
_BROWSERS = [("EdgA/", "Edge"), ("Edg/", "Edge"), ("SamsungBrowser", "Samsung Internet"), ("OPR/", "Opera"),
             ("Firefox/", "Firefox"), ("FxiOS", "Firefox"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"),
             ("Safari/", "Safari")]
_GENERIC_MODELS = {"k", "linux", "u", "wv", "mobile", ""}


def _browser(ua: str) -> str | None:
    for token, name in _BROWSERS:
        if token in ua:
            return name
    if "CaptiveNetworkSupport" in ua or "wispr" in ua.lower():
        return "captive-portal window"
    return None


def describe(ua: str | None) -> str:
    if not ua:
        return "Unknown device"
    parts: list[str] = []
    m = _IOS.search(ua)
    if m:
        parts.append(m.group(1))
        parts.append("iOS " + m.group(2).replace("_", "."))
    elif "Android" in ua:
        m = _ANDROID.search(ua)
        version = m.group(1) if m and m.group(1) else ""
        model = (m.group(2).split(" Build/")[0].strip() if m else "")
        parts.append(("Android " + version).strip())
        if model.lower() not in _GENERIC_MODELS:
            parts.append(model[:40])
    elif "Windows NT" in ua:
        parts.append("Windows PC")
    elif "CrOS" in ua:
        parts.append("Chromebook")
    elif "Macintosh" in ua:
        parts.append("Mac")  # iPads in desktop mode also report Macintosh
    elif "Linux" in ua:
        parts.append("Linux")
    else:
        parts.append("Unknown device")
    b = _browser(ua)
    if b:
        parts.append(b)
    return " · ".join(parts)[:120]
