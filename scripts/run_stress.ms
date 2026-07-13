/*  Batch wrapper: run the LightMatch in-Max STRESS via Max's Python.
    3dsmaxbatch scripts\run_stress.ms — verdict in scripts\_stress_result.txt. */
(
    local repo = systemTools.getEnvVariable "LIGHTMATCH_MAX"
    if repo == undefined or repo == "" do repo = @"C:\Users\aasis\lightmatch-max"
    local py = repo + @"\scripts\stress_max.py"
    format "LightMatch stress: executing %\n" py
    python.ExecuteFile py
    format "LightMatch stress: python returned.\n"
)
