"""Total token usage across Hermes (all profiles) and OpenClaw (all agents). Read-only."""
import sqlite3, os, json, glob
from compression import zstd   # Python 3.14+

def ro(p): return sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True)
rows = []

# Hermes: session_model_usage in each profile's state.db
H = os.path.join(os.environ["LOCALAPPDATA"], "hermes")
for name, p in [("hermes/default", f"{H}/state.db")] + [
        (f"hermes/{os.path.basename(os.path.dirname(x))}", x) for x in sorted(glob.glob(f"{H}/profiles/*/state.db"))]:
    i, o, r = ro(p).execute("SELECT COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),"
                            "COALESCE(SUM(cache_read_tokens),0) FROM session_model_usage").fetchone()
    rows.append((name, i, o, r))

# OpenClaw: usage objects inside transcript_events (plain or zstd-compressed JSON)
for p in sorted(glob.glob(os.path.expanduser("~/.openclaw/agents/*/agent/openclaw-agent.sqlite"))):
    i = o = r = 0
    for ev, z in ro(p).execute("SELECT event_json, event_zstd FROM transcript_events"):
        try:
            raw = ev if ev else zstd.decompress(z).decode("utf-8")
            if '"usage"' not in raw: continue
            d = json.loads(raw); u = (d.get("message") or d).get("usage") or {}
            i += u.get("input", 0) or 0; o += u.get("output", 0) or 0; r += u.get("cacheRead", 0) or 0
        except Exception: pass
    rows.append((f"openclaw/{p.split('agents')[-1].split(os.sep)[1] if os.sep in p.split('agents')[-1] else p.split('/')[-3]}", i, o, r))

print(f"{'source':22}{'input':>14}{'output':>12}{'cache_read':>16}")
for n, i, o, r in rows: print(f"{n:22}{i:>14,}{o:>12,}{r:>16,}")
hi = sum(x[1] for x in rows if x[0].startswith("hermes")), sum(x[2] for x in rows if x[0].startswith("hermes")), sum(x[3] for x in rows if x[0].startswith("hermes"))
oi = sum(x[1] for x in rows if x[0].startswith("openclaw")), sum(x[2] for x in rows if x[0].startswith("openclaw")), sum(x[3] for x in rows if x[0].startswith("openclaw"))
print("-" * 64)
print(f"{'HERMES total':22}{hi[0]:>14,}{hi[1]:>12,}{hi[2]:>16,}")
print(f"{'OPENCLAW total':22}{oi[0]:>14,}{oi[1]:>12,}{oi[2]:>16,}")
print(f"{'GRAND TOTAL':22}{hi[0]+oi[0]:>14,}{hi[1]+oi[1]:>12,}{hi[2]+oi[2]:>16,}")
print(f"\nGrand input+output (excl. cache): {hi[0]+oi[0]+hi[1]+oi[1]:,}")
