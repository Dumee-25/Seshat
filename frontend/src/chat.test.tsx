/**
 * The chat's controls were traps before Phase 8: Clear erased the
 * conversation on one misclick, a question could not be abandoned, and a
 * citation named a database row instead of a moment.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { Chat } from "./Chat";

vi.mock("./api");
const mocked = vi.mocked(api);

const noop = () => {};

beforeEach(() => {
  mocked.getChatHistory.mockResolvedValue([]);
  mocked.clearChat.mockResolvedValue(new Response(null));
});

async function renderChat() {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Chat onCite={noop} />);
  });
  return utils;
}

const ask = (question: string) => {
  fireEvent.change(screen.getByPlaceholderText(/What did I already try/), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
};

describe("citations", () => {
  it("names the moment rather than the session id", async () => {
    mocked.getChatHistory.mockResolvedValue([
      {
        role: "assistant",
        text: "You tried it.",
        citations: [
          {
            session_id: 12,
            started_at: "2026-08-01T16:30:00Z",
            what_changed: "Added SMOTE oversampling.",
          },
        ],
      },
    ]);
    await renderChat();

    const cite = await screen.findByRole("button", { name: /Added SMOTE oversampling/ });
    expect(cite.textContent).toContain("Added SMOTE oversampling.");
    expect(cite.textContent).not.toBe("session 12");
  });

  it("truncates a long summary instead of stretching the chip", async () => {
    const long = "A".repeat(120);
    mocked.getChatHistory.mockResolvedValue([
      {
        role: "assistant",
        text: "x",
        citations: [
          { session_id: 1, started_at: "2026-08-01T16:30:00Z", what_changed: long },
        ],
      },
    ]);
    await renderChat();

    const cite = await screen.findByRole("button", { name: /A{10,}/ });
    expect(cite.textContent!.length).toBeLessThan(80);
    expect(cite.textContent).toContain("…");
  });

  it("falls back to the session id when there is no summary", async () => {
    mocked.getChatHistory.mockResolvedValue([
      {
        role: "assistant",
        text: "x",
        citations: [{ session_id: 7, started_at: "not a date", what_changed: null }],
      },
    ]);
    await renderChat();
    expect(await screen.findByRole("button", { name: "session 7" })).toBeTruthy();
  });

  it("hands the session id back when a citation is followed", async () => {
    const onCite = vi.fn();
    mocked.getChatHistory.mockResolvedValue([
      {
        role: "assistant",
        text: "x",
        citations: [
          { session_id: 42, started_at: "2026-08-01T16:30:00Z", what_changed: "did a thing" },
        ],
      },
    ]);
    await act(async () => {
      render(<Chat onCite={onCite} />);
    });

    fireEvent.click(await screen.findByRole("button", { name: /did a thing/ }));
    expect(onCite).toHaveBeenCalledWith(42);
  });
});

describe("answers", () => {
  it("renders markdown rather than a wall of text", async () => {
    mocked.postChat.mockResolvedValue({
      answer: "## Heading\n\n- one\n- two",
      citations: [],
      papers: [],
    });
    const { container } = await renderChat();

    ask("what did I try?");

    await waitFor(() => expect(container.querySelector("h2")).toBeTruthy());
    expect(container.querySelectorAll("li")).toHaveLength(2);
  });

  it("does not treat the question itself as markdown", async () => {
    // The user's own text is shown verbatim; only answers are rendered.
    mocked.postChat.mockResolvedValue({ answer: "ok", citations: [], papers: [] });
    const { container } = await renderChat();

    ask("why is my_var_name * 2 wrong?");
    await screen.findByText("ok"); // let the answer land before asserting

    expect(screen.getByText("why is my_var_name * 2 wrong?")).toBeTruthy();
    expect(container.querySelectorAll(".msg.user em")).toHaveLength(0);
  });
});

describe("asking", () => {
  it("refuses to send an empty question", async () => {
    await renderChat();
    expect(screen.getByRole("button", { name: "Ask" }).hasAttribute("disabled")).toBe(true);
  });

  it("sends on Enter and keeps Shift+Enter for a new line", async () => {
    mocked.postChat.mockResolvedValue({ answer: "ok", citations: [], papers: [] });
    await renderChat();
    const box = screen.getByPlaceholderText(/What did I already try/);

    fireEvent.change(box, { target: { value: "first line" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(mocked.postChat).not.toHaveBeenCalled();

    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(mocked.postChat).toHaveBeenCalledOnce());
  });

  it("uses a textarea so multi-line questions are possible", async () => {
    await renderChat();
    expect(screen.getByPlaceholderText(/What did I already try/).tagName).toBe("TEXTAREA");
  });
});

describe("a question in flight", () => {
  /** A request that never settles unless its signal aborts. */
  const hang = (_q: string, signal?: AbortSignal) =>
    new Promise<never>((_, reject) => {
      signal?.addEventListener("abort", () => reject(new DOMException("x", "AbortError")));
    });

  it("offers a cancel instead of Ask", async () => {
    mocked.postChat.mockImplementation(hang);
    await renderChat();
    ask("slow question");

    expect(await screen.findByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ask" })).toBeNull();
  });

  it("counts elapsed seconds so a slow model does not look hung", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocked.postChat.mockImplementation(hang);
    await renderChat();
    ask("slow question");

    await screen.findByText(/Thinking/);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByText(/Thinking · 3s/)).toBeTruthy();
    vi.useRealTimers();
  });

  it("treats a cancel as a choice, not an error", async () => {
    mocked.postChat.mockImplementation(hang);
    const { container } = await renderChat();
    ask("slow question");

    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Ask" })).toBeTruthy());
    expect(container.querySelector(".chat-error")).toBeNull();
  });

  it("still reports a genuine failure", async () => {
    mocked.postChat.mockRejectedValue(new Error("Ollama is not running"));
    await renderChat();
    ask("a question");

    expect(await screen.findByText("Ollama is not running")).toBeTruthy();
  });
});

describe("clearing", () => {
  const withHistory = () =>
    mocked.getChatHistory.mockResolvedValue([
      { role: "user", text: "a question", citations: [] },
    ]);

  it("takes two steps rather than erasing on one click", async () => {
    withHistory();
    await renderChat();
    await screen.findByText("a question");

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(mocked.clearChat).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Erase all" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Keep" })).toBeTruthy();
  });

  it("backs out without touching the conversation", async () => {
    withHistory();
    await renderChat();
    await screen.findByText("a question");

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));

    expect(mocked.clearChat).not.toHaveBeenCalled();
    expect(screen.getByText("a question")).toBeTruthy();
  });

  it("erases once confirmed", async () => {
    withHistory();
    await renderChat();
    await screen.findByText("a question");

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    fireEvent.click(screen.getByRole("button", { name: "Erase all" }));

    await waitFor(() => expect(mocked.clearChat).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByText("a question")).toBeNull());
  });

  it("cannot be started on an empty conversation", async () => {
    await renderChat();
    expect(screen.getByRole("button", { name: "Clear" }).hasAttribute("disabled")).toBe(true);
  });
});

afterEach(() => {
  vi.useRealTimers();
});
