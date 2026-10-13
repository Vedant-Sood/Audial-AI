# Local installation

Use Python 3.11 or 3.12 x64 on Windows. Extract the project into a writable folder and run setup.bat. It creates .venv and installs matched Torch/torchaudio 2.8.0 plus app dependencies. An available nvidia-smi selects CUDA 12.6 wheels; otherwise it selects CPU wheels. PyTorch's CUDA availability is checked after installation. Use setup.bat --cpu if the driver cannot support that build.

Setup downloads FAST's multilingual Whisper tiny, ECAPA and MediaPipe hand/body tasks and installs the newly trained bundled sign checkpoint. --no-models leaves pretrained downloads for later Models-page actions; --preset BALANCED selects Whisper small and --preset ACCURATE selects medium. Larger presets require more memory and local performance checks. CREMA-D emotion weights are already in the ZIP; tone recognition defaults to off and can be enabled in Settings.

Run run.bat for the desktop or run_browser.bat for the local browser companion on port 8765. An existing desktop can open its companion with a dynamic port, displayed in the address. Choose capture explicitly; startup records nothing. The desktop floating sign window can stay above other apps. Browser floating mode needs a Chromium browser with Document Picture-in-Picture.

For browser meetings select the meeting tab and enable Share tab audio. Browser app/system-audio sharing depends on OS support. The desktop's System audio action uses the default playback device through SoundCard loopback. That backend needs validation on the target laptop. For text in other apps, copy it and choose Use clipboard on the sign page. See README for the included Chrome/Edge text extension.

Allow microphone/camera access for desktop applications in Windows privacy settings. Choose the device index in Settings after inspecting Diagnostics. Imported audio can exercise captions without a microphone. Inference uses local models after setup.

The source ZIP is not a prebuilt executable. build_windows.bat installs optional build dependencies and invokes the PyInstaller specification, including browser files and trained weights. No Windows binary or installer was built/verified in this Linux environment. Use Diagnostics locally to test CUDA, device capture and inference before relying on measured performance.
