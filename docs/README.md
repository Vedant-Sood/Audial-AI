# Audial-AI documentation

[Project overview and installation](../README.md)

Audial-AI contains the Windows accessibility workspace, its browser companion
and the Kandha captioning/haptic prototype. Start with the guide for the task
you want to perform.

| Task | Guide |
| --- | --- |
| Install the local workspace | [Installation](local_installation.md) and the root README's current Windows distribution notes |
| Use captions, recordings, exports and ISL | [User guide](user_guide.md) |
| Try Kandha without hardware | [Kandha user guide](kandha/USER_GUIDE.md), [demo script](kandha/DEMO_SCRIPT.md) |
| Understand capture, models and services | [Architecture](architecture.md) |
| Work with ISL vocabulary | [ISL format and scope](isl.md) |
| Understand voice cues shared with Kandha | [Voice engine](sanket.md) |
| Inspect data and model assumptions | [Datasets](datasets.md), [model cards](model_cards.md) |
| Reproduce voice-model training | [Voice training](voice_emotion_training.md), [local training](local_training.md) |
| Investigate a failure | [Troubleshooting](troubleshooting.md) |
| Run development checks | [Testing](testing.md) |
| Review the recorded Windows release checks | [0.5.0 validation](validation-0.5.0.md) |
| Review Kandha measurements and firmware | [Kandha validation](kandha/VALIDATION.md), [firmware](../firmware/kandha/README.md) |
| Understand consent, local storage and model limits | [Privacy](privacy.md), [limitations](limitations.md) |
| Check dependencies and redistribution | [License notices](../LICENSE_NOTICES.md), [contributing](../CONTRIBUTING.md) |

## Read status carefully

Kandha's virtual and simulated stole support a hardware-free prototype.
The physical stole and real Bluetooth path are not hardware-qualified.
Voice-expression estimates have corpus-specific evaluations; those results
do not establish natural-conversation or Indian-language accuracy.
The bundled ISL vocabulary is limited rather than a general sentence translator.

Versioned validation reports describe the source and environment named in
each report. Use the current Actions results or release metadata to choose a
build. Model installation and any gated upstream access are separate from
installing the application. This index does not claim a new application,
hardware or model-validation run.
