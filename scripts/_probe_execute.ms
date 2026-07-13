-- Compare sys.path in python.Execute (string) vs python.ExecuteFile (path).
-- These should be the SAME Python context but historically have differed in embedded hosts.

(
    python.Execute "import sys, json; _p1 = list(sys.path); _p2 = 'numpy' in str(_p1); import lightmatch_max.bootstrap as _b; _miss = _b._missing(); _out = repr({'has_usersite_in_path': any('Python311' in p and 'site-packages' in p for p in sys.path), 'sys_path_len': len(sys.path), 'missing': _miss, 'first5_path': _p1[:5]}); python.Execute \"import sys; open(r'C:\\Users\\Aasish Muchala\\Desktop\\3dspluginlight\\scripts\\_exec_probe.txt','w',encoding='utf-8').write(repr({'usersite_in_path': any('Python311' in p and 'site-packages' in p for p in sys.path), 'sys_path_len': len(sys.path), 'first5_path': list(sys.path)[:5]}))\""
    python.ExecuteFile @"C:\Users\Aasish Muchala\Desktop\3dspluginlight\scripts\_probe_paths.py"
)