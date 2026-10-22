# 0011 · The prototype runs without hardware: a simulated stole is the default link

**Decision.** `KandhaSettings.link` defaults to `"simulated"`: the bridge runs on an in-process
`SimulatedStole` (a `MockStole` that pairs, reports a slowly draining battery, can be sent out of
range and can press its pads). The Stole screen offers **Simulate** buttons. `"bluetooth"` (the
real `bleak` link) is an explicit setting labelled *experimental, untested with hardware*.
The virtual stole on screen always shows every tap, whichever link is chosen.

**Why.** The user's direction during the build: this is a prototype; the software must carry out
its own features and need not be ready to pair with real hardware. A default that tried to use
Bluetooth would show failures on machines without an adapter and prove nothing.

**Kept.** The bridge, the firmware and the protocol stay in the repository and in the tests, so
the step to hardware is a settings change plus a flashed board, not new code.
