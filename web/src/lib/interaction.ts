// Run something once, on the visitor's first interaction (scroll, wheel, touch, key, pointer).
// Used to keep heavy chunks (GSAP and the hero, the easter eggs) out of everything that is fetched
// before the visitor does anything: the home bundle budget counts that total.
const EVENTS = ["scroll", "wheel", "touchmove", "keydown", "pointerdown"] as const;

export function onFirstInteraction(cb: () => void): () => void {
  let done = false;
  const fire = () => {
    if (done) return;
    done = true;
    cleanup();
    cb();
  };
  const cleanup = () => EVENTS.forEach((e) => window.removeEventListener(e, fire));
  EVENTS.forEach((e) => window.addEventListener(e, fire, { passive: true }));
  return () => {
    done = true;
    cleanup();
  };
}

/** Keys and clicks that arrive while a lazy module is still loading, replayed once it is in. */
export const pending = { keys: [] as string[], coin: false };

/** Let the browser run other tasks (input, paint) before the next step of a long set-up. */
export function yieldToMain(): Promise<void> {
  const sched = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
  return sched?.yield ? sched.yield() : new Promise((resolve) => setTimeout(resolve, 0));
}
