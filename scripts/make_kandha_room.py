"""Make a SIMULATED multichannel room for the Recorded audio mode and for tests.

    python -m scripts.make_kandha_room --out room.wav --array stereo --talk 270:0.5:3 --talk 90:4:3
    python -m scripts.make_kandha_room --out pod.wav --array quad --talk 0:0.5:3 --talk 90:4:3 --talk 180:7.5:3 --talk 270:11:3

Each --talk is bearing:start:seconds (bearing in degrees clockwise from straight ahead:
front 0, right 90, behind 180, left 270). Voices are LibriSpeech readings from the repository's
test fixtures. Writes the WAV and a .json beside it with the array geometry and the true
bearings; the Recorded mode reads both and labels everything it shows "Simulated".
"""
import argparse

from app.kandha.direction import ArrayGeometry
from app.kandha.room_synth import Room, Talker, voices, write


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--array", choices=["stereo", "quad"], default="quad")
    parser.add_argument("--spacing", type=float, default=0.03, help="stereo microphone spacing in metres")
    parser.add_argument("--talk", action="append", required=True, help="bearing:start_s:duration_s")
    parser.add_argument("--noise-db", type=float, default=-45.0)
    args = parser.parse_args()
    geometry = ArrayGeometry.stereo(args.spacing) if args.array == "stereo" else ArrayGeometry.quad()
    names = voices()
    talkers = []
    for i, spec in enumerate(args.talk):
        bearing, start, duration = (float(x) for x in spec.split(":"))
        talkers.append(Talker(bearing % 360, start, duration, names[i % len(names)]))
    path = write(args.out, Room(geometry, talkers, noise_db=args.noise_db))
    print(f"wrote {path} and {path.with_suffix('.json')} (SIMULATED, {geometry.channels} channels)")


if __name__ == "__main__":
    main()
