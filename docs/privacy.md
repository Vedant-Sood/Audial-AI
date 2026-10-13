# Privacy

Normal inference uses installed model files on this computer. The app disables Hugging Face telemetry and pyannote metrics, sets offline mode before inference, and has no remote inference service or analytics client. Downloads are explicit setup/Install/CLI actions and send normal download requests to the selected providers.

The browser companion listens **only on 127.0.0.1**. It accepts requests from its local Host/Origin and checks each browser window's capture-session identifier. Browser audio is uploaded as short PCM WAV packets to that local process, not to a remote server. Microphone, shared tab/app audio and system loopback start only after an explicit action. Stop closes capture and finalizes already captured speech. Imported audio remains local.

The extension reads selected text, or up to 2,000 characters of main page text, only after its Open page text button is clicked. It opens that text in the local companion using a URL fragment, which the companion removes from its address. It stores only the chosen companion port in extension storage. Desktop Use clipboard reads clipboard text only when clicked. These text actions do not fabricate speech transcript entries.

Microphone audio, webcam frames, live poses and speaker centroids stay in memory. Raw session recordings are not saved. Models, preferences and explicitly saved transcript JSON live in %LOCALAPPDATA%/AccessibilityAI on Windows or ~/.local/share/AccessibilityAI elsewhere; ACCESSIBILITY_AI_HOME can choose another directory. The browser retains completed captions in server memory until a new browser session or process exit. Exports are written when requested.

Saved/exported transcripts can include spoken words, timestamps, user-provided speaker names, similarity scores and optional measured pitch/level/tone. Speaker labels are session clusters, not identified people. Inferred tone is uncertain, optional, and kept separate from quoted words. Deleting a saved session does not remove independently exported copies or browser downloads.

Model installation downloads upstream assets and records revision/hash metadata. A locally configured HF_TOKEN is used only when a provider requires authentication; tokens are not stored in app preferences or transcripts. The optional gated pyannote model requires the provider's acceptance process first and is not downloaded by setup.

If the selected user-data folder or downloads directory is cloud-synced, that separate sync software controls any upload of your saved files. The app does not change those settings. Device and performance diagnostics write local reports; microphone/camera tests are explicitly invoked from Diagnostics.
