/*  Switch to V-Ray (3dsmaxbatch defaults to Arnold in Max 2026 even when V-Ray is
    active in the UI) then run the smoke. Verdict still goes to
    scripts\_smoke_result.txt. */
(
    local repo = systemTools.getEnvVariable "LIGHTMATCH_MAX"
    if repo == undefined or repo == "" do repo = @"C:\Users\Aasish Muchala\Desktop\3dspluginlight"
    local helper = repo + @"\scripts\_ensure_vray.py"
    local smoke = repo + @"\scripts\smoke_max.py"
    format "LightMatch smoke (vray): switching renderer via %\n" helper
    python.ExecuteFile helper
    format "LightMatch smoke (vray): executing %\n" smoke
    python.ExecuteFile smoke
    format "LightMatch smoke (vray): python returned.\n"
)
