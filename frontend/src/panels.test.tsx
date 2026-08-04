/**
 * The rule these tests exist to defend: a panel that could not load must
 * never render an empty state claiming the project has nothing in it.
 *
 * Every panel got this wrong at some point — first by swallowing the error
 * outright, then by gating the failure branch on a flag set in `.finally()`,
 * which is already true by the time the error lands.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { Code } from "./Code";
import { Data } from "./Data";
import { Papers } from "./Papers";

vi.mock("./api");
const mocked = vi.mocked(api);

const boom = () => Promise.reject(new Error("Failed to fetch"));
const noop = () => {};

beforeEach(() => {
  // Default everything to "loads fine and is empty"; each test overrides.
  mocked.getFiles.mockResolvedValue([]);
  mocked.getFileChanges.mockResolvedValue([]);
  mocked.getFileHistory.mockResolvedValue([]);
  mocked.getArtifacts.mockResolvedValue([]);
  mocked.getPapers.mockResolvedValue([]);
});

describe("Code", () => {
  it("reports a failed load instead of claiming there are no files", async () => {
    mocked.getFiles.mockImplementation(boom);
    mocked.getFileChanges.mockImplementation(boom);
    render(<Code onCite={noop} />);

    expect(await screen.findByText(/Couldn't load the code panel/)).toBeTruthy();
    expect(screen.queryByText(/No watched code files/)).toBeNull();
    expect(screen.queryByText(/Nothing captured yet/)).toBeNull();
  });

  it("fails the whole panel when only one of its two loads fails", async () => {
    // A half-loaded panel is still a panel asserting something false.
    mocked.getFileChanges.mockImplementation(boom);
    render(<Code onCite={noop} />);

    expect(await screen.findByText(/Couldn't load the code panel/)).toBeTruthy();
  });

  it("says the project is empty only once it has actually loaded", async () => {
    render(<Code onCite={noop} />);
    expect(await screen.findByText(/No watched code files/)).toBeTruthy();
    expect(screen.queryByText(/Couldn't load/)).toBeNull();
  });

  it("shows a per-file history failure without blanking the panel", async () => {
    mocked.getFiles.mockResolvedValue([
      { name: "train.py", path: "train.py", type: "file", changes: 2 },
    ]);
    mocked.getFileHistory.mockImplementation(boom);
    render(<Code onCite={noop} />);

    fireEvent.click(await screen.findByText("train.py"));

    expect(await screen.findByText("Failed to fetch")).toBeTruthy();
    expect(screen.queryByText(/Couldn't load the code panel/)).toBeNull();
  });
});

describe("Data", () => {
  it("reports a failed load instead of claiming there is no data", async () => {
    mocked.getArtifacts.mockImplementation(boom);
    render(<Data onCite={noop} />);

    expect(await screen.findByText(/Couldn't load the data panel/)).toBeTruthy();
    expect(screen.queryByText(/No data tracked yet/)).toBeNull();
  });

  it("says there is no data only once it has actually loaded", async () => {
    render(<Data onCite={noop} />);
    expect(await screen.findByText(/No data tracked yet/)).toBeTruthy();
  });
});

describe("Papers", () => {
  it("reports a failed first load instead of claiming there are no papers", async () => {
    mocked.getPapers.mockImplementation(boom);
    render(<Papers />);

    expect(await screen.findByText(/Couldn't load papers and links/)).toBeTruthy();
    expect(screen.queryByText(/No papers or links yet/)).toBeNull();
  });

  it("keeps the list on screen when a later refresh fails", async () => {
    // Adding a link refreshes the list. If that refresh fails, the papers
    // already on screen are still real and must not be replaced by an error.
    mocked.getPapers.mockResolvedValue([
      { id: 1, title: "SMOTE paper", path: "papers/smote.pdf", added_at: null, source: "pdf" },
    ]);
    render(<Papers />);
    expect(await screen.findByText("SMOTE paper")).toBeTruthy();

    mocked.getPapers.mockImplementation(boom);
    mocked.addLink.mockImplementation(boom);
    fireEvent.change(screen.getByPlaceholderText(/Paste a URL/), {
      target: { value: "https://example.com/post" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add link/i }));

    await waitFor(() => expect(screen.getByText("Failed to fetch")).toBeTruthy());
    expect(screen.getByText("SMOTE paper")).toBeTruthy();
    expect(screen.queryByText(/Couldn't load papers/)).toBeNull();
  });
});

describe("keyboard reachability", () => {
  it("renders rows as buttons, not clickable divs", async () => {
    mocked.getArtifacts.mockResolvedValue([
      { id: 1, path: "results/metrics.csv", name: "metrics.csv", kind: "result", created_at: null },
    ]);
    render(<Data onCite={noop} />);

    const row = await screen.findByRole("button", { name: /metrics\.csv/ });
    expect(row.tagName).toBe("BUTTON");
  });

  it("marks the selected file with aria-current", async () => {
    mocked.getFiles.mockResolvedValue([
      { name: "train.py", path: "train.py", type: "file", changes: 1 },
    ]);
    render(<Code onCite={noop} />);

    const file = await screen.findByRole("button", { name: /train\.py/ });
    expect(file.getAttribute("aria-current")).toBeNull();
    fireEvent.click(file);
    await waitFor(() => expect(file.getAttribute("aria-current")).toBe("true"));
  });

  it("exposes directory open state to assistive tech", async () => {
    mocked.getFiles.mockResolvedValue([
      {
        name: "src",
        path: "src",
        type: "dir",
        children: [{ name: "features.py", path: "src/features.py", type: "file" }],
      },
    ]);
    render(<Code onCite={noop} />);

    const dir = await screen.findByRole("button", { name: /src/ });
    expect(dir.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(dir);
    await waitFor(() => expect(dir.getAttribute("aria-expanded")).toBe("false"));
  });
});
