"""Compare sys.path when running under python.Execute (the toolbar button's form)."""
import sys
lines = []
lines.append("--- from python.Execute (string) ---")
lines.append(f"sys.path has user site-packages: {any('Python311' in p and 'site-packages' in p for p in sys.path)}")
lines.append(f"sys.path length: {len(sys.path)}")
lines.append("first 8 sys.path entries:")
for p in sys.path[:8]:
    lines.append(f"  {p}")
try:
    import lightmatch_max.bootstrap as _b
    missing = _b._missing()
except Exception as e:
    missing = [f"ERR: {e!r}"]
lines.append(f"bootstrap._missing() -> {missing}")
with open(r"C:\Users\Aasish Muchala\Desktop\3dspluginlight\scripts\_exec_probe.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))