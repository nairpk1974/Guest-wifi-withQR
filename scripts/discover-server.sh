#!/usr/bin/env bash
# Phase 1 discovery for the Ubuntu Docker server (read-only). Output: ./discovery-server-<host>.txt
OUT="discovery-server-$(hostname)-$(date +%Y%m%d).txt"
{
  echo "== OS";            lsb_release -a 2>/dev/null; uname -a
  echo "== Docker";        docker version 2>&1 | head -20; docker compose version 2>&1
  echo "== Resources";     nproc; free -h; df -h
  echo "== Addresses";     ip -br addr
  echo "== Routes";        ip route
  echo "== DNS";           resolvectl status 2>/dev/null | head -30 || cat /etc/resolv.conf
  echo "== Listening";     sudo ss -tulpn
  echo "== Containers";    docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
  echo "== Docker nets";   docker network ls; docker network inspect bridge 2>/dev/null | grep -E 'Subnet|Gateway'
  echo "== Firewall";      sudo ufw status verbose 2>/dev/null; sudo iptables -S 2>/dev/null | head -50
  echo "== Time";          timedatectl
  for h in "$@"; do echo "== Reachability $h"; ping -c 3 -W 2 "$h"; done
} > "$OUT" 2>&1
echo "Wrote $OUT  (usage: $0 <fgt-blr-ip> <fgt-hyd-ip> to include ping tests)"
