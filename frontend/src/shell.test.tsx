/**
 * The shell's job is to describe the system's state without overstating it:
 * the connection, the queue, and a broken install.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { App } from "./App";
import { Health } from "./Health";

vi.mock("./api");
const mocked = vi.mocked(api);

const STATUS: api.Status = {
  project: "demo",
  root: "/tmp/demo",
  sessions: 61,
  queued: 0,
  papers: 2,
  gpu_busy: false,
  cpu_fallback: false,
};

const HEALTHY: api.SetupStatus = {
  ollama_installed: true,
  ollama_running: true,
  missing_models: [],
  ok: true,
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mocked.getStatus.mockResolvedValue(STATUS);
  mocked.getSetup.mockResolvedValue(HEALTHY);
  mocked.getTimeline.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  vi.useRealTimers();
});

/**
 * App fires two independent polls on mount (status and setup). Rendering
 * inside `act` lets both settle before assertions, instead of landing as
 * stray state updates mid-test.
 */
async function renderApp() {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<App />);
  });
  return utils;
}

/** Advance the poll clock with the resulting re-renders inside `act`. */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("status bar", () => {
  it("reports a live connection once a poll succeeds", async () => {
    const { container } = await renderApp();
    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(container.querySelector(".dot")!.className).toContain("live");
  });

  it("stops claiming to be connected once polling fails", async () => {
    // The bug this defends: a failed poll left the stale status in place and
    // nothing cleared it, so the footer kept saying "Connected" forever.
    const { container } = await renderApp();
    await screen.findByText("Connected");

    mocked.getStatus.mockRejectedValue(new Error("Failed to fetch"));
    await tick(5000);

    await waitFor(() => expect(screen.getByText("Not responding")).toBeTruthy());
    expect(container.querySelector(".dot")!.className).toContain("lost");
  });

  it("keeps the last known counts while disconnected", async () => {
    // They are stale, but they are still the most recent truth available.
    await renderApp();
    await screen.findByText("61 sessions");

    mocked.getStatus.mockRejectedValue(new Error("Failed to fetch"));
    await tick(5000);

    await screen.findByText("Not responding");
    expect(screen.getByText("61 sessions")).toBeTruthy();
  });

  it("recovers when the server comes back", async () => {
    const { container } = await renderApp();
    await screen.findByText("Connected");
    mocked.getStatus.mockRejectedValue(new Error("down"));
    await tick(5000);
    await screen.findByText("Not responding");

    mocked.getStatus.mockResolvedValue(STATUS);
    await tick(5000);

    await waitFor(() => expect(screen.getByText("Connected")).toBeTruthy());
    expect(container.querySelector(".dot")!.className).toContain("live");
  });
});

describe("the queued count", () => {
  it("says nothing extra when the queue is empty", async () => {
    await renderApp();
    expect((await screen.findByText(/queued/)).textContent).toBe("0 queued");
  });

  it("blames a busy GPU when that is what is holding the queue", async () => {
    // A count that never moves during a training run looks broken; it isn't.
    mocked.getStatus.mockResolvedValue({ ...STATUS, queued: 3, gpu_busy: true });
    await renderApp();
    expect((await screen.findByText(/queued/)).textContent).toBe(
      "3 queued · waiting for the GPU",
    );
  });

  it("says it is processing when the GPU is free", async () => {
    mocked.getStatus.mockResolvedValue({ ...STATUS, queued: 3, gpu_busy: false });
    await renderApp();
    expect((await screen.findByText(/queued/)).textContent).toBe("3 queued · processing");
  });

  it("names CPU fallback rather than implying the GPU is in use", async () => {
    mocked.getStatus.mockResolvedValue({ ...STATUS, queued: 2, cpu_fallback: true });
    await renderApp();
    expect((await screen.findByText(/queued/)).textContent).toBe(
      "2 queued · processing on CPU",
    );
  });

  it("explains the GPU-idle policy on hover", async () => {
    mocked.getStatus.mockResolvedValue({ ...STATUS, queued: 1 });
    await renderApp();
    const el = await screen.findByText(/queued/);
    expect(el.getAttribute("title")).toContain("never competes with a training run");
  });
});

describe("health banner", () => {
  it("stays out of the way when the install is fine", async () => {
    const { container } = await renderApp();
    await screen.findByText("Connected");
    expect(container.querySelector(".health")).toBeNull();
  });

  it("appears when Ollama cannot answer", async () => {
    mocked.getSetup.mockResolvedValue({
      ollama_installed: true,
      ollama_running: false,
      missing_models: ["qwen3:8b"],
      ok: false,
    });
    await renderApp();
    expect(
      await screen.findByText(/Capture is running, but journaling and search are not/),
    ).toBeTruthy();
  });

  it("tells the user their work is still being recorded", async () => {
    // Capture surviving a failed install is the design; say so, or the banner
    // reads as "nothing is working".
    render(<Health setup={{ ...HEALTHY, ok: false, ollama_running: false }} />);
    expect(screen.getByText(/Your work is still being recorded/)).toBeTruthy();
  });

  it("points at the installer when Ollama is absent", () => {
    render(
      <Health
        setup={{
          ollama_installed: false,
          ollama_running: false,
          missing_models: ["qwen3:8b"],
          ok: false,
        }}
      />,
    );
    expect(screen.getByText(/Install Ollama/)).toBeTruthy();
    // Advising a pull would be useless: nothing is there to pull with.
    expect(screen.queryByText(/ollama pull/)).toBeNull();
  });

  it("advises a pull only once Ollama is actually running", () => {
    render(
      <Health
        setup={{
          ollama_installed: true,
          ollama_running: true,
          missing_models: ["qwen3:8b", "nomic-embed-text"],
          ok: false,
        }}
      />,
    );
    expect(screen.getByText("ollama pull qwen3:8b")).toBeTruthy();
    expect(screen.getByText("ollama pull nomic-embed-text")).toBeTruthy();
  });

  it("is announced to assistive tech", () => {
    const { container } = render(
      <Health setup={{ ...HEALTHY, ok: false, ollama_running: false }} />,
    );
    expect(container.querySelector(".health")!.getAttribute("role")).toBe("status");
  });
});

describe("navigation", () => {
  it("exposes every view as a button with the current one marked", async () => {
    await renderApp();
    await screen.findByText("Connected");

    const timeline = screen.getByRole("button", { name: "Timeline" });
    expect(timeline.tagName).toBe("BUTTON");
    expect(timeline.getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("button", { name: "Chat" }).getAttribute("aria-current")).toBeNull();
  });
});
