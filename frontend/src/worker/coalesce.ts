/**
 * Latest-wins request coalescing.
 *
 * The map asks for positions on every animation frame. Computing all of them is
 * cheap, but doing it once per frame is not, and dropping the NEWEST request
 * would leave the map showing a stale instant — the one bug a user notices
 * immediately. So: while a run is in flight, only the most recent submission is
 * kept, and it is always processed.
 */

export interface LatestRunner<T> {
  /** Submit work. Replaces any submission that has not started yet. */
  submit(value: T): void;
  /** Resolves when nothing is running and nothing is queued. */
  whenIdle(): Promise<void>;
}

export function createLatestRunner<T>(process: (value: T) => Promise<void>): LatestRunner<T> {
  let pending: { value: T } | null = null;
  let running = false;
  let idleWaiters: Array<() => void> = [];

  const settleIdleWaiters = (): void => {
    if (running || pending !== null) return;
    const waiters = idleWaiters;
    idleWaiters = [];
    for (const resolve of waiters) resolve();
  };

  const loop = async (): Promise<void> => {
    running = true;
    while (pending !== null) {
      const next = pending;
      pending = null;
      try {
        await process(next.value);
      } catch {
        // A failed run must not wedge the loop; the caller reports errors on its
        // own channel. The next submission still gets processed.
      }
    }
    running = false;
    settleIdleWaiters();
  };

  return {
    submit(value: T): void {
      pending = { value };
      if (!running) void loop();
    },
    whenIdle(): Promise<void> {
      if (!running && pending === null) return Promise.resolve();
      return new Promise<void>((resolve) => {
        idleWaiters.push(resolve);
      });
    },
  };
}
