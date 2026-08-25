/**
 * Triage has to be cheap: a third of inferred intents are expected to be
 * wrong, so a researcher opening the cockpit after a week faces a queue of
 * them. That means the keyboard, and it means undo.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { Timeline } from "./Timeline";

vi.mock("./api");
const mocked = vi.mocked(api);

function session(id: number, overrides: Partial<api.TimelineItem["meta"]> = {}) {
  return {
    ts: `2026-08-0${id}T09:00:00Z`,
    kind: "session" as const,
    id,
    title: `Session ${id}`,
    subtitle: null,
    meta: {
      entry_id: id * 10,
      intent: `guess ${id}`,
      intent_status: "inferred",
      intent_confidence: 0.8,
      ...overrides,
    },
  };
}

beforeEach(() => {
  mocked.getTimeline.mockResolvedValue({
    items: [session(1), session(2), session(3)],
    total: 3,
  });
  mocked.setIntent.mockResolvedValue({
    id: 10,
    intent: "x",
    intent_status: "confirmed",
  });
  mocked.resetIntent.mockResolvedValue({
    id: 10,
    intent: "x",
    intent_status: "inferred",
  });
  mocked.getSession.mockResolvedValue({
    session: { id: 1, started_at: "2026-08-01T09:00:00Z", ended_at: null, status: "processed" },
    entries: [],
    events: [],
  });
});

async function renderTimeline() {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Timeline />);
  });
  await screen.findByText("Session 1");
  return utils;
}

const rows = () => [...document.querySelectorAll<HTMLElement>(".row[tabindex]")];

describe("keyboard triage", () => {
  it("gives every row focus so triage never needs the mouse", async () => {
    await renderTimeline();
    expect(rows()).toHaveLength(3);
    rows()[0].focus();
    expect(document.activeElement).toBe(rows()[0]);
  });

  it.each([
    ["ArrowDown", 1],
    ["j", 1],
  ])("moves down with %s", async (key, delta) => {
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key });
    expect(document.activeElement).toBe(rows()[delta]);
  });

  it.each(["ArrowUp", "k"])("moves up with %s", async (key) => {
    await renderTimeline();
    rows()[2].focus();
    fireEvent.keyDown(rows()[2], { key });
    expect(document.activeElement).toBe(rows()[1]);
  });

  it("stays put at the ends rather than wrapping", async () => {
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "ArrowUp" });
    expect(document.activeElement).toBe(rows()[0]);
  });

  it("confirms with c", async () => {
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "c" });
    // No text argument: confirming means "the guess stands as written".
    await waitFor(() => expect(mocked.setIntent).toHaveBeenCalledWith(10));
  });

  it("opens the editor with e, seeded with the model's guess", async () => {
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "e" });

    const box = await screen.findByPlaceholderText(/What were you actually trying to do/);
    expect((box as HTMLTextAreaElement).value).toBe("guess 1");
  });

  it("opens the evidence with Enter", async () => {
    await renderTimeline();
    const toggle = screen.getAllByRole("button", { name: /show evidence/ })[0];
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "Enter" });

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /hide evidence/ })[0],
      ).toBeTruthy(),
    );
  });

  it("ignores keys typed inside the intent editor", async () => {
    // The bug this defends: typing "confirm" in the editor would otherwise
    // fire confirm, edit and undo on the way through.
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "e" });
    const box = await screen.findByPlaceholderText(/What were you actually trying to do/);

    mocked.setIntent.mockClear();
    fireEvent.keyDown(box, { key: "c" });
    fireEvent.keyDown(box, { key: "u" });

    expect(mocked.setIntent).not.toHaveBeenCalled();
    expect(mocked.resetIntent).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText(/What were you actually trying to do/)).toBeTruthy();
  });

  it("does not confirm an entry that was already reviewed", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { intent_status: "confirmed" })],
      total: 1,
    });
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "c" });
    expect(mocked.setIntent).not.toHaveBeenCalled();
  });

  it("undoes a reviewed entry with u", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { intent_status: "corrected" })],
      total: 1,
    });
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "u" });
    await waitFor(() => expect(mocked.resetIntent).toHaveBeenCalledWith(10));
  });

  it("does not undo an entry that has not been reviewed", async () => {
    await renderTimeline();
    rows()[0].focus();
    fireEvent.keyDown(rows()[0], { key: "u" });
    expect(mocked.resetIntent).not.toHaveBeenCalled();
  });
});

describe("review controls", () => {
  it("offers confirm and edit only while unreviewed", async () => {
    await renderTimeline();
    expect(screen.getAllByRole("button", { name: "confirm" })).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "undo" })).toBeNull();
  });

  it("offers undo once reviewed", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { intent_status: "confirmed" })],
      total: 1,
    });
    await renderTimeline();
    expect(screen.getByRole("button", { name: "undo" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "confirm" })).toBeNull();
  });

  it("surfaces a failed review instead of silently doing nothing", async () => {
    mocked.setIntent.mockRejectedValue(new Error("No such entry"));
    await renderTimeline();
    fireEvent.click(screen.getAllByRole("button", { name: "confirm" })[0]);
    expect(await screen.findByText("No such entry")).toBeTruthy();
  });
});

/**
 * The row's whole job is to keep a guess from reading as a recorded fact. Both
 * halves of that are easy to undo by accident — a styling tidy-up that drops
 * the italic block, or a "let's just show the number" revert.
 */
describe("fact and inference stay distinguishable", () => {
  it("sets an unconfirmed guess apart from the recorded title", async () => {
    const { container } = await renderTimeline();
    const row = rows()[0];

    // The title is the record; the guess is a claim, and it lives in its own
    // block rather than as a dimmer line of the same kind.
    expect(row.querySelector(".row-title")!.textContent).toBe("Session 1");
    expect(row.querySelector(".intent-text")!.textContent).toBe("guess 1");
    expect(container.querySelector(".intent")).toBeTruthy();
  });

  it("folds a confirmed intent into the record", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { intent_status: "confirmed" })],
      total: 1,
    });
    const { container } = await renderTimeline();

    // No longer a guess: the rule, the italic and the meter all go.
    expect(container.querySelector(".intent")).toBeNull();
    expect(container.querySelector(".meter")).toBeNull();
    expect(container.querySelector(".intent-confirmed")!.textContent).toContain(
      "guess 1",
    );
  });

  it("still shows an intent that cannot be reviewed", async () => {
    // A backfilled row has no entry id, so nothing can be confirmed — but the
    // reason is the one thing a reader came for.
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { entry_id: undefined })],
      total: 1,
    });
    const { container } = await renderTimeline();
    expect(container.querySelector(".intent-confirmed")!.textContent).toContain(
      "guess 1",
    );
    expect(screen.queryByRole("button", { name: "confirm" })).toBeNull();
  });
});

describe("confidence", () => {
  it("states a band rather than a decimal", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { intent_confidence: 0.4 })],
      total: 1,
    });
    const { container } = await renderTimeline();

    expect(container.querySelector(".intent-band")!.textContent).toBe("low");
    expect(screen.queryByText(/0\.4/)).toBeNull();
  });

  it("keeps the exact value reachable for anyone comparing two guesses", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { intent_confidence: 0.4 })],
      total: 1,
    });
    const { container } = await renderTimeline();
    expect(container.querySelector(".meter")!.getAttribute("title")).toBe(
      "confidence 0.40",
    );
  });

  it("fills one segment per band", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [
        session(1, { intent_confidence: 0.4 }),
        session(2, { intent_confidence: 0.6 }),
        session(3, { intent_confidence: 0.95 }),
      ],
      total: 3,
    });
    const { container } = await renderTimeline();
    const filled = [...container.querySelectorAll(".meter")].map(
      (m) => m.querySelectorAll(".meter-seg.on").length,
    );
    expect(filled).toEqual([1, 2, 3]);
  });

  it("draws no meter when the model reported no confidence", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1, { intent_confidence: null })],
      total: 1,
    });
    const { container } = await renderTimeline();
    expect(container.querySelector(".intent-text")).toBeTruthy();
    expect(container.querySelector(".meter")).toBeNull();
  });
});

describe("paging and filters", () => {
  it("reports how much of the feed is on screen", async () => {
    mocked.getTimeline.mockResolvedValue({ items: [session(1)], total: 63 });
    await renderTimeline();
    expect(screen.getByText("1 of 63")).toBeTruthy();
  });

  it("offers more only when there is more", async () => {
    await renderTimeline();
    expect(screen.queryByRole("button", { name: /Load/ })).toBeNull();
  });

  it("asks for a bigger page when told to load more", async () => {
    mocked.getTimeline.mockResolvedValue({
      items: [session(1), session(2), session(3)],
      total: 120,
    });
    await renderTimeline();

    fireEvent.click(screen.getByRole("button", { name: /Load 50 more/ }));

    await waitFor(() =>
      expect(mocked.getTimeline).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 100 }),
      ),
    );
  });

  it("filters by kind and starts that narrower feed from the top", async () => {
    mocked.getTimeline.mockResolvedValue({ items: [session(1)], total: 120 });
    await renderTimeline();
    fireEvent.click(screen.getByRole("button", { name: /Load 50 more/ }));
    await waitFor(() =>
      expect(mocked.getTimeline).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 100 }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "paper" }));

    await waitFor(() =>
      expect(mocked.getTimeline).toHaveBeenLastCalledWith(
        expect.objectContaining({ kinds: ["paper"], limit: 50 }),
      ),
    );
  });

  it("debounces the search rather than querying per keystroke", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderTimeline();
    const box = screen.getByPlaceholderText(/Search titles/);

    mocked.getTimeline.mockClear();
    for (const value of ["s", "sm", "smo", "smot", "smote"]) {
      fireEvent.change(box, { target: { value } });
    }
    expect(mocked.getTimeline).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    await waitFor(() =>
      expect(mocked.getTimeline).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "smote" }),
      ),
    );
    vi.useRealTimers();
  });

  it("says nothing matches rather than claiming the project is empty", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderTimeline();
    mocked.getTimeline.mockResolvedValue({ items: [], total: 0 });

    fireEvent.change(screen.getByPlaceholderText(/Search titles/), {
      target: { value: "nothing matches this" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(await screen.findByText(/Nothing matches these filters/)).toBeTruthy();
    expect(screen.queryByText(/Nothing recorded yet/)).toBeNull();
    vi.useRealTimers();
  });

  it("reports an unreachable API instead of an empty feed", async () => {
    mocked.getTimeline.mockRejectedValue(new Error("Failed to fetch"));
    await act(async () => {
      render(<Timeline />);
    });
    expect(await screen.findByText(/Can't reach the Seshat API/)).toBeTruthy();
    expect(screen.queryByText(/Nothing recorded yet/)).toBeNull();
  });
});
