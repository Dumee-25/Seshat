import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Every test mounts into the same document; unmount between them so a stale
// tree can't satisfy the next test's queries.
afterEach(cleanup);

// jsdom has no layout, so anything that scrolls needs a stand-in. Several
// components call this on mount (the timeline jumping to a citation, the chat
// sticking to the bottom).
Element.prototype.scrollIntoView = () => {};
