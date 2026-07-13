/*  Switch to V-Ray (3dsmaxbatch defaults to Arnold in Max 2026 even when V-Ray is
    active in the UI) then run the full end-to-end stress. Verdict goes to
    scripts\_stress_result.txt. */
(
    local repo = systemTools.getEnvVariable "LIGHTMATCH_MAX"
    if repo == undefined or repo == "" do repo = @"C:\Users\Aasish Muchala\Desktop\3dspluginlight"
    local helper = repo + @"\scripts\_ensure_vray.py"
    local stress = repo + @"\scripts\stress_max.py"
    format "LightMatch stress (vray): switching renderer via %\n" helper
    python.ExecuteFile helper
    format "LightMatch stress (vray): executing %\n" stress
    python.ExecuteFile stress
    format "LightMatch stress (vray): python returned.\n"
)
