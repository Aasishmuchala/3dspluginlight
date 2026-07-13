/* Run a single python.Execute (string) — the toolbar button's form — and report sys.path */
(
    python.Execute "import sys, lightmatch_max.bootstrap as _b\nmissing = _b._missing()\nout = 'has_usersite=' + str(any('Python311' in p and 'site-packages' in p for p in sys.path)) + ' path_len=' + str(len(sys.path)) + ' missing=' + repr(missing) + ' first3=' + repr(sys.path[:3])\nopen(r'C:\\Users\\Aasish Muchala\\Desktop\\3dspluginlight\\scripts\\_exec_probe.txt', 'w', encoding='utf-8').write(out)"
)