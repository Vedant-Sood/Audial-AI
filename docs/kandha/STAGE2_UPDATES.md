# Kandha: agreed updates for Stage 2

A tracking list of the design changes Team Resonance agreed after the Hackcessible India 2026
Stage 1 judges' feedback (November 2026). Each item is agreed, not built. Tick an item once it is
implemented, or note why it was dropped. [DESIGN.md](DESIGN.md) remains the design of record
until each item is merged into it.

Two items are still open questions: keeping the mic pod, and keeping named emotions in Review.

## Direction sensing

- [ ] **Mic pod.** A small rigid board at the collarbone, under a foam windscreen, holds a few
      MEMS microphones in fixed positions. It replaces microphones sewn into loose fabric, which
      shift with the body and pick up rustle. *(Open question: keep the pod, or seat map only.)*
- [ ] **Self-noise control.** A motion sensor in the pod pauses direction estimates while the
      wearer moves. The firmware ignores microphone frames while the stole's own motors are
      vibrating.
- [ ] **Angles only.** The pod estimates direction on the ESP32-S3 and sends only an angle over
      Bluetooth, never audio. Needs a bench test to confirm the chip can do this.
- [ ] **Two direction sources.** The seat map set with the textured pads stays the baseline. The
      pod's angle fills in unknown voices and updates the map when someone moves, through the
      existing `SeatSource` interface and its angle-to-zone mapping.
- [ ] **Crosstalk tap.** When two people talk at once, play a distinct crosstalk pattern on both
      shoulders instead of guessing, then tap whoever keeps talking.
- [ ] **Turn correction.** The pod's motion sensor rotates the seat map when the wearer turns their
      body, so taps stay correct relative to the shoulders.

## Garment build

- [ ] All electronics on one removable carrier strip with a single connector.
- [ ] Motors in silicone pockets, with strain relief wherever wires bend.
- [ ] Cotton or khadi stole that can be washed once the carrier is lifted out.

## Tone cues

- [ ] Live cues report only measurable changes against that person's usual voice: louder, softer,
      hesitating, long silence.
- [ ] Named emotion estimates appear only in Review, off by default, at 80% confidence or more.
      *(Open question: keep them in Review, or drop them entirely.)*
- [ ] Stop describing the feature as "emotion recognition" anywhere in the app or documents.

## Privacy

Guiding rule: **Kandha gives the wearer the same notes a hearing student could take, never a full
record of what others said.**

- [ ] **Live captions are ephemeral.** Captions stay in memory only and are wiped after five
      minutes. Full transcripts are never kept. The same window powers "What did I miss?"
- [ ] **Bookmarks.** One tap on a pad keeps a caption line as a note. This compensates for the
      wearer being unable to write while lip-reading.
- [ ] **Automatic redaction before saving.** Bookmarks are saved with names, numbers and similar
      details removed, with no speaker labels and no tone data. There is no review step and no
      unredacted copy.
- [ ] **"Kandha, off the record."** Anyone in the room can say it. It wipes the last five minutes
      of captions for everyone and cancels bookmarks from that window. It blocks bookmarks,
      one-tap saving and copy-paste of caption text until someone says **"Kandha, back on"** or the
      session ends. Live captions keep showing, and the wearer can still type notes in their own
      words.
- [ ] **Feedback.** The stole's light reads as "captioning", not "recording", and changes colour
      while off the record. The wearer feels a distinct tap when off the record starts and ends.
- [ ] **Lecture mode exception.** If the professor agrees once per course, the full lecture
      transcript can be kept as course material.
- [ ] **Practicum mode.** Nothing is ever saved.
- [ ] **Storage.** Saved notes are encrypted on the laptop. Audio is never recorded.
- [ ] Measure how often "Kandha, off the record" is detected in noisy rooms and with Indian
      accents, and report it.

## Corrections to carry into the documents

- [ ] Parts cost about ₹2,200–2,650 before the mic pod and motion sensor (DESIGN.md section 5.1),
      not the ₹1,500–2,000 quoted in the Stage 1 video.
- [ ] Fabric is cotton or khadi, not wool or silk.
- [ ] Speech detection and noise handling run on the laptop. The stole's chip plays taps, reads
      pads and, with the pod, estimates direction.
- [ ] The 98% right-speaker figure (docs/sanket.md) comes from stitched recordings with no
      interruptions, overlap or noise. Always state that when quoting it.
