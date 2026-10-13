# Troubleshooting

**Python not found:** install Python 3.11 x64 with the launcher, then rerun setup.bat. The project uses its own `.venv`; it does not modify a global Python installation.

**No CUDA / DLL error:** update the NVIDIA driver through its normal supported installer and rerun hardware checks. Paired Torch/torchaudio 2.8 CUDA wheels are selected by setup when NVIDIA is detected. CTranslate2 needs CUDA 12/cuDNN 9 libraries; the app exposes Torch's DLL directory on Windows. Try FAST / CPU or `setup.bat --cpu` if the CUDA path is still unavailable. The presence of nvidia-smi alone is not proof that PyTorch/ASR acceleration works.

**Microphone fails:** allow desktop apps under Windows privacy settings; close another app holding exclusive capture; inspect indexes in Diagnostics and save the desired index in Settings. The input path requests 16-kHz mono. Some devices/host APIs need a compatible Windows recording format or another device. Hardware validation failure is recorded, not hidden.

**Webcam fails:** allow camera access for desktop apps, close conflicting camera applications, then try another camera index. Pose assets must be installed first. The webcam starts only after its button is clicked.

**No captions:** install the model required by the chosen preset. Install ECAPA or choose Speaker backend=off. Speak at normal volume; noise/very quiet input may fail VAD. A language code can be set explicitly. Raw ASR scores and a speaker colour do not guarantee correctness.

**Caption queue warnings:** choose FAST, disable partial updates, or use a faster device. Dropped input keeps timestamp gaps. A queue-full warning means some speech was not captioned; no artificial transcript is generated to fill it.

**Download interrupted / model not installed:** retry Install when capture/training is stopped. `.installing` folders retain resumable downloads but are not treated as installed. Gated models require upstream acceptance and a locally configured HF_TOKEN. Do not paste tokens into saved app documents.

**Wrong sign / uncertain label:** the bundled model knows only four isolated signs. Show both hands and upper body, record a complete sign, and review/edit the result before speaking. Collect signer-independent validation data before expanding its role.

**TTS cannot speak:** install a Windows local speech voice and ensure a valid output device. SAPI5 is used on Windows. Linux eSpeak/voice configuration was not validated as a Windows proxy. Audio capture pauses during playback to reduce feedback.

**Training fails:** dataset NPZ needs a real-data provenance JSON with matching schema beside it and nonempty train/val/test partitions. On CUDA OOM reduce batch, increase accumulation and resume latest.pt. Stop live capture before training. For a new dataset/config create a new output directory.

**SmartScreen / signing:** builds are unsigned until a publisher signs them. This project does not bypass Windows security. Use the Python source launch workflow while a signed installer is unavailable.

**Cloud MediaPipe GLES error:** a normal Linux machine needs libgles2/libegl1. During this cloud run the missing libgles2 package was extracted into a scoped dependency directory and provided through LD_LIBRARY_PATH. No such adjustment is required for the Windows wheel.
