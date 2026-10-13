// Ordered ISL playback. Unknown text is a real queue item, never skipped.
import { validateSequence } from "./light-box.js";

export function expandISLPlan(plan) {
  if (!plan || plan.language !== "ISL" || !Array.isArray(plan.steps) || !Array.isArray(plan.sequences)) {
    throw new Error("The display requires an Indian Sign Language plan.");
  }
  return plan.steps.map(step => {
    if (typeof step.text !== "string" || !step.text.trim()) throw new Error("Missing original input text.");
    if (step.kind === "text") return {...step};
    if (step.kind === "pose") {
      const sequence = plan.sequences[step.sequence_index];
      return {...step, sequence: validateSequence(sequence)};
    }
    if (step.kind === "video" && /^\/api\/sign-media\/[a-f0-9]{64}$/.test(step.url)) return {...step};
    throw new Error("Unsupported ISL playback step.");
  });
}

export class ISLPlayback {
  constructor({show, start, pause, advanceFrame, remaining, idle = () => {},
               setTimer = (fn, delay) => globalThis.setTimeout(fn, delay),
               clearTimer = id => globalThis.clearTimeout(id), reducedMotion = false}) {
    Object.assign(this, {show, start, pauseMedia: pause, advanceFrame, remaining, idle, setTimer, clearTimer});
    this.queue = []; this.current = null; this.timer = null;
    this.paused = false; this.speed = 1; this.reducedMotion = reducedMotion;
  }

  clearTimerOnly() {
    if (this.timer !== null) this.clearTimer(this.timer);
    this.timer = null;
  }

  stop() {
    this.clearTimerOnly(); this.pauseMedia();
    this.queue = []; this.current = null; this.paused = false; this.idle();
  }

  enqueue(plan, {append = false} = {}) {
    const steps = expandISLPlan(plan); // Validate before replacing a working plan.
    if (!append) this.stop();
    this.queue.push(...steps);
    if (!this.current) this.next(!this.paused);
  }

  stopCaptions() {
    this.queue = this.queue.filter(step => !step.from_captions);
    if (this.current?.from_captions) this.next(!this.paused);
  }

  next(play = true) {
    this.clearTimerOnly(); this.pauseMedia();
    this.current = this.queue.shift() ?? null;
    if (!this.current) {this.idle(); return;}
    this.show(this.current); this.paused = !play;
    if (play) this.play();
  }

  play() {
    this.clearTimerOnly(); this.paused = false;
    if (!this.current) {this.next(); return;}
    if (this.reducedMotion) return;
    this.start(this.current, this.speed);
    const milliseconds = this.remaining(this.current);
    if (Number.isFinite(milliseconds)) {
      this.timer = this.setTimer(() => {this.timer = null; this.next();}, Math.max(1, milliseconds) / this.speed);
    }
  }

  pause() {
    this.clearTimerOnly(); this.pauseMedia(); this.paused = true;
  }

  step() {
    this.pause();
    if (!this.current) {this.next(false); return;}
    if (this.current.kind === "text" || this.advanceFrame(this.current)) this.next(false);
  }

  restart() {
    this.pause();
    if (this.current) {this.show(this.current); this.play();}
  }

  setSpeed(speed) {
    if (!Number.isFinite(speed) || speed < .25 || speed > 2) throw new Error("Use a speed between 0.25 and 2.");
    const resume = !this.paused;
    this.pause(); this.speed = speed;
    if (resume) this.play();
  }

  setReducedMotion(value) {
    this.reducedMotion = Boolean(value);
    if (this.reducedMotion) this.pause();
  }
}
