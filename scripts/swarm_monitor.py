#!/usr/bin/env python3
"""Swarm Monitor CLI — Observabilité locale structurée
Usage:
  python scripts/swarm_monitor.py --watch    # tail -f les logs swarm_trace.jsonl
  python scripts/swarm_monitor.py --stats    # agrège métriques dernière heure
  python scripts/swarm_monitor.py --recover <chain_id>  # replay d'un swarm_id
"""
import json, time, sys, os, argparse
from pathlib import Path
from collections import defaultdict

LOGS_DIR = Path(__file__).parent.parent / "logs"
TRACE_FILE = LOGS_DIR / "swarm_trace.jsonl"

def watch():
    """Tail -f lisible du fichier swarm_trace"""
    import subprocess
    if not TRACE_FILE.exists():
        print(f"⏳ En attente de {TRACE_FILE}...")
        TRACE_FILE.parent.mkdir(exist_ok=True)
        TRACE_FILE.touch()
    try:
        proc = subprocess.Popen(["tail", "-f", str(TRACE_FILE)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("🔄 Swarm Monitor — watch mode (Ctrl+C pour quitter)")
        print("─" * 50)
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                agent = ev.get("agent", "?")
                event = ev.get("event", "?")
                to = ev.get("to", "")
                metrics = ev.get("metrics", {})
                inf = metrics.get("inference_s", "")
                vram = metrics.get("vram_peak_mb", "")
                parts = [f"[{agent}]"]
                if event == "handoff":
                    parts.append(f"→ {to}" if to else "→ ?")
                elif event == "complete":
                    parts.append("✅ DONE")
                else:
                    parts.append(event)
                if inf:
                    parts.append(f"({inf}s")
                    if vram:
                        parts.append(f"{vram}MiB")
                    parts.append(")")
                print(" ".join(parts))
            except json.JSONDecodeError:
                print(f"⚠️  {line[:100]}")
    except KeyboardInterrupt:
        print("\n👋 Arrêté.")

def stats(hours=1):
    """Agrège les métriques des N dernières heures"""
    if not TRACE_FILE.exists():
        print("📭 Aucun fichier swarm_trace.jsonl trouvé.")
        return
    cutoff = time.time() - hours * 3600
    chains = defaultdict(lambda: {"handoffs": 0, "total_inference_s": 0.0, "max_vram_mb": 0, "total_swap_s": 0.0, "agents_seen": set()})
    events = []
    with open(TRACE_FILE) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                ev = json.loads(line)
                events.append(ev)
            except json.JSONDecodeError:
                continue
    
    recent = [e for e in events if e.get("ts", "") >= time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(cutoff))]
    
    for ev in recent:
        cid = ev.get("chain_id", "?")
        m = ev.get("metrics", {})
        chains[cid]["handoffs"] += 1
        chains[cid]["agents_seen"].add(ev.get("agent", ""))
        chains[cid]["total_inference_s"] += m.get("inference_s", 0)
        chains[cid]["max_vram_mb"] = max(chains[cid]["max_vram_mb"], m.get("vram_peak_mb", 0))
    if not chains:
        print("📭 Aucune chaîne trouvée dans la dernière heure.")
        return
    print(f"📊 Stats (dernière {int(hours)}h) — {len(recent)} événements, {len(chains)} chaînes")
    print("─" * 50)
    for cid, data in sorted(chains.items(), key=lambda x: -x[1]["total_inference_s"])[:5]:
        agents = ", ".join(sorted(data["agents_seen"]))
        print(f"  [{cid[:8]}] {data['handoffs']} handoffs | {data['total_inference_s']:.1f}s inf | {data['max_vram_mb']}MiB VRAM | {agents}")

def recover(chain_id):
    """Replay le contexte d'un swarm_id depuis les logs"""
    if not TRACE_FILE.exists():
        print("📭 swarm_trace.jsonl introuvable.")
        return
    events = []
    with open(TRACE_FILE) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                ev = json.loads(line)
                if ev.get("chain_id", "") == chain_id:
                    events.append(ev)
            except json.JSONDecodeError:
                continue
    if not events:
        print(f"📭 Aucun événement pour chain_id={chain_id}")
        return
    print(f"🔁 Replay chain_id={chain_id} ({len(events)} événements)")
    print("─" * 50)
    for ev in events:
        agent = ev.get("agent", "?")
        event = ev.get("event", "?")
        to = ev.get("to", "")
        ts = ev.get("ts", "")
        m = ev.get("metrics", {})
        inf = m.get("inference_s", "")
        vram = m.get("vram_peak_mb", "")
        h = ev.get("context_hash", "")[:8]
        line = f"  [{ts}] {agent}"
        if event == "handoff":
            line += f" → {to}" if to else " → ?"
        elif event == "complete":
            line += " ✅ FIN"
        else:
            line += f" {event}"
        if inf:
            line += f" ({inf}s {vram}MiB)"
        if h:
            line += f" ctx={h}"
        print(line)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Swarm Monitor CLI")
    parser.add_argument("--watch", action="store_true", help="Tail -f temps réel")
    parser.add_argument("--stats", action="store_true", help="Agrège métriques dernière heure")
    parser.add_argument("--recover", type=str, help="Replay d'un chain_id")
    args = parser.parse_args()
    
    if args.watch:
        watch()
    elif args.stats:
        stats()
    elif args.recover:
        recover(args.recover)
    else:
        parser.print_help()
