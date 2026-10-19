import argparse
import os
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--install-model")
    p.add_argument("--model-root")
    p.add_argument("--accepted-conditions", action="store_true")
    p.add_argument("--train-task", choices=["sign", "prosody", "diarization"])
    p.add_argument("--train-config")
    p.add_argument("--control")
    p.add_argument("--resume")
    p.add_argument("--hardware-check", action="store_true")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--setup-models", action="store_true", help="Install and verify the complete supported model catalogue")
    p.add_argument("--forget-model-token", action="store_true", help="Remove the current user's saved model credential")
    p.add_argument("--validate-local", action="store_true")
    p.add_argument("--browser", action="store_true")
    p.add_argument("--open-browser", action="store_true")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--smoke-test", action="store_true", help="Validate native startup and bundled models without recording")
    p.add_argument("--verify-emotion", action="store_true", help="Run the installed WavLM model on the supplied speech recording without capturing audio")
    p.add_argument("--verify-inference", action="store_true", help="Run real captions, expression and prosody offline without recording")
    p.add_argument("--verify-live-inference", action="store_true", help="Run real streaming captions/expression offline using software-fed supplied speech, without a microphone")
    args = p.parse_args()
    if args.forget_model_token:
        from app.utils.credentials import forget_token
        forget_token()
        return
    if args.setup_models:
        import json
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["TRANSFORMERS_OFFLINE"] = "0"
        from app.models.catalogue import CatalogueInstaller
        from app.models.manager import ModelManager
        states = CatalogueInstaller(ModelManager(args.model_root),
                    progress=lambda event: print(json.dumps(event), flush=True)).run(args.accepted_conditions)
        failed = any(item["state"] in {"failed", "paused"} for item in states.values())
        sys.exit(1 if failed else 0)
    if args.list_devices:
        import json
        import sounddevice as sd
        print(json.dumps([{"index": index, "name": device["name"]}
                          for index, device in enumerate(sd.query_devices())
                          if device["max_input_channels"]]), flush=True)
        return
    if args.install_model:
        os.environ["HF_HUB_OFFLINE"] = "0"
        from app.models.manager import ModelManager
        ModelManager(args.model_root).install(args.install_model, accepted=args.accepted_conditions)
        return
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if args.verify_inference or args.verify_live_inference:
        from app.services.validation import verify_inference
        verify_inference(stream=args.verify_live_inference)
        return
    if args.verify_emotion:
        import json
        import math
        from app.inference.emotion import VoiceEmotion
        from accessibilityai_upgrade.audio import read_wav
        from app.utils.paths import project_root
        model = VoiceEmotion()
        if model.model.bundle["feature_version"] not in {"wavlm-layer-mean-std-v1","ssl-global-temporal-v1","ssl-acoustic-stack-v1"}:
            raise RuntimeError("Complete WavLM installation in Setup & models first.")
        prediction = model.predict(read_wav(project_root() / "assets" / "evaluation_sample.wav"))
        values = list(prediction["probabilities"].values())
        if len(values) != 6 or not all(math.isfinite(p) for p in values) or abs(sum(values)-1) > .001:
            raise RuntimeError("The installed emotion model returned invalid probabilities.")
        print(json.dumps({"voice_emotion_inference":"PASS", "model":model.source_name,
                          "tone":prediction["tone"],"confidence":prediction["confidence"],
                          "class_count":len(values),"microphone_started":False}),flush=True)
        return
    if args.browser:
        from app.services.browser import main as browser_main
        browser_main(args.port, args.open_browser)
        return
    if args.train_task:
        import yaml
        from pathlib import Path
        from training.runner import train
        train(yaml.safe_load(Path(args.train_config).read_text()), args.train_task, args.resume, args.control)
        return
    if args.hardware_check:
        from scripts.hardware_check import main
        main()
        return
    if args.validate_local:
        from scripts.local_validation import main
        main()
        return
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Audial-AI")
    app.setOrganizationName("Audial-AI")
    window = MainWindow(auto_setup=not args.smoke_test)
    window.show()
    if args.smoke_test:
        import json
        import numpy as np
        import platform
        from app.inference.emotion import VoiceEmotion
        from app.utils.paths import project_root
        from app.utils.config import Settings
        from PySide6.QtCore import QTimer
        window.reduce_motion.setChecked(True)
        window.play_signs("धन्यवाद team")
        if window.pose.points is None:
            raise RuntimeError("Bundled native ISL playback did not start.")
        model = VoiceEmotion()
        silence = model.predict(np.zeros(16000, dtype=np.float32))
        if silence["tone"] != "uncertain":
            raise RuntimeError("Silence must not receive an emotion label.")
        from app import __version__
        print(json.dumps({"version": __version__, "platform": platform.system(),
                          "native_ui": "PASS", "isl_playback": "PASS", "silence_abstention": "PASS",
                          "microphone_started": window.engine.running,
                          "caption_model_installed": window.manager.installed("whisper-tiny")}), flush=True)
        QTimer.singleShot(200, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
