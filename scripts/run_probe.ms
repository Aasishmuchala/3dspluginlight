/* Debug — run the V-Ray class probe */
(
    local repo = systemTools.getEnvVariable "LIGHTMATCH_MAX"
    if repo == undefined or repo == "" do repo = @"C:\Users\Aasish Muchala\Desktop\3dspluginlight"
    python.ExecuteFile (repo + @"\scripts\_probe_renderer.py")
)
