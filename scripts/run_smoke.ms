/*  Batch wrapper: run the LightMatch in-Max smoke via Max's Python.
    Invoked headlessly:  3dsmaxbatch scripts\run_smoke.ms
    (The Python writes scripts\_smoke_result.txt — the runner reads THAT, never
    batch stdout, which 3dsmaxbatch swallows.) */
(
    local repo = systemTools.getEnvVariable "LIGHTMATCH_MAX"
    if repo == undefined or repo == "" do repo = @"C:\Users\aasis\lightmatch-max"
    local smoke = repo + @"\scripts\smoke_max.py"
    format "LightMatch smoke: executing %\n" smoke
    python.ExecuteFile smoke
    format "LightMatch smoke: python returned.\n"
)
