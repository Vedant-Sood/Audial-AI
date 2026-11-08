# Kandha: 90-second demo video script

Uses **Demo mode** (no microphone) and the **virtual stole**. Record the Kandha window (it
opens at 1280 × 760; crop to 1280 × 720 for a 720p video), dark theme, caption size L. Scripted
tone estimates are labelled "scripted" on screen; say so in the voice-over.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:08 | Kandha Live screen, welcome card. | "Vikram is a deaf psychology student who lip-reads. In seminars he loses the first words of every new speaker while his eyes search the room." |
| 0:08–0:16 | Click **Watch the seminar demo** (on the welcome card, or **Demos** in the dock). Dr Rao's caption appears in blue; the room diagram lights the front seat; the virtual stole's **F** zone taps twice. | "Kandha is a laptop app and a haptic scarf. When someone new speaks, two taps at the front say *new voice*…" |
| 0:16–0:26 | Priya appears (red, left); Arjun (green, right). Each new voice: two taps at the front, then the seat lights up. | "…and once a seat is set, the shoulder on that person's side gets one firm tap. His eyes go to the right face before the words are gone." |
| 0:26–0:34 | The queue strip glows amber; the stole squeezes both shoulders (`queue_ack`). | "Press Q, or the queue pad on the scarf: *I want to speak*. The stole squeezes both shoulders to say it is on." |
| 0:34–0:46 | Priya speaks again: one tap on the **left** shoulder. Dr Rao: one tap at the **front**. The strip stays amber; Dr Rao says "Vikram, you wanted to add something?"; the strip clears, one squeeze. | "Every change of speaker is one tap on that side. No buzzing: Kandha taps for changes, not states." |
| 0:46–0:54 | The silence: two gentle ticks on both shoulders, then Arjun on the right. | "A long silence means the floor is open. Two gentle ticks." |
| 0:54–1:10 | Click **Demos** in the dock, then **Watch the practicum demo**. The client speaks; the collarbone zone swells slowly (*voice softened*), later a flutter (*hesitation*) and three quick taps (*voice rose*). Captions show tone chips marked *scripted*. | "In practicum, how a client's voice changes is clinical information. A slow swell at the collarbone: the voice softened. A flutter: hesitation. Three quick taps: the voice rose. These are hints about the voice, never claims about feelings." |
| 1:10–1:20 | **Review** screen: timeline lanes for voices, cues, tone estimates, queue moments, taps and seats; the consent checkbox. | "Afterwards, the whole session on one timeline. Nothing is saved without everyone's consent." |
| 1:20–1:30 | **Stole** screen: the simulated stole paired, battery, **Learn the taps**. End card. | "The scarf is still a prototype: today the virtual stole shows every tap. Kandha. Keep your eyes on the person." |

Notes for filming: tick **Play the demo voices aloud** (in the Demos dialog) only if the room
is quiet; switching demos carries nothing over from the one that was playing; the demos run
about 38 s (seminar) and 32 s (practicum), so trim. The seminar rows narrate every tap that
demo plays. The practicum row narrates only its three tone cues; before and between them the
stole also taps the front twice for each of the two new voices (the client and Vikram), once
for each of the client's two later turns, and ticks both shoulders for a silence. Both are
recorded through the real scheduler in [validation/demo-taps.json](validation/demo-taps.json) by
`python -m scripts.record_kandha_demos`, which fails if a demo's taps change or the narrated taps
stop coming in this order, so the voice-over matches what the screen does.
