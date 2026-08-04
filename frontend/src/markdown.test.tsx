import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./markdown";

/** Render and hand back the root, so tests can query structure directly. */
function md(text: string): HTMLElement {
  const { container } = render(<Markdown text={text} />);
  return container.querySelector(".md")!;
}

const textOf = (nodes: Iterable<Element>) => [...nodes].map((n) => n.textContent);

describe("blocks", () => {
  it("wraps plain lines in a paragraph", () => {
    const root = md("just a sentence");
    expect(textOf(root.querySelectorAll("p"))).toEqual(["just a sentence"]);
  });

  it("joins consecutive lines into one paragraph", () => {
    const root = md("a model wraps\nits prose at some width");
    expect(textOf(root.querySelectorAll("p"))).toEqual([
      "a model wraps its prose at some width",
    ]);
  });

  it("splits paragraphs on a blank line", () => {
    expect(textOf(md("first\n\nsecond").querySelectorAll("p"))).toEqual([
      "first",
      "second",
    ]);
  });

  it("renders headings at their level", () => {
    const root = md("# one\n## two\n###### six");
    expect(textOf(root.querySelectorAll("h1"))).toEqual(["one"]);
    expect(textOf(root.querySelectorAll("h2"))).toEqual(["two"]);
    expect(textOf(root.querySelectorAll("h6"))).toEqual(["six"]);
  });

  it("does not treat seven hashes as a heading", () => {
    const root = md("####### not a heading");
    expect(root.querySelectorAll("h1,h2,h3,h4,h5,h6")).toHaveLength(0);
    expect(textOf(root.querySelectorAll("p"))).toEqual(["####### not a heading"]);
  });

  it("renders a fenced code block verbatim", () => {
    const root = md("```python\nx = 1\n\ny = 2\n```");
    expect(textOf(root.querySelectorAll("pre"))).toEqual(["x = 1\n\ny = 2"]);
  });

  it("does not apply inline markup inside a code block", () => {
    const root = md("```\nweights = a_b_c * 2\n```");
    expect(root.querySelectorAll("em")).toHaveLength(0);
    expect(root.querySelector("pre")!.textContent).toBe("weights = a_b_c * 2");
  });

  it("runs an unterminated fence to the end rather than dropping it", () => {
    // A truncated or cancelled answer must still show the code it got to.
    const root = md("intro\n\n```\nhalf a code block");
    expect(textOf(root.querySelectorAll("pre"))).toEqual(["half a code block"]);
  });
});

describe("lists", () => {
  it("groups bullets into one list", () => {
    const root = md("- alpha\n- beta");
    expect(root.querySelectorAll("ul")).toHaveLength(1);
    expect(textOf(root.querySelectorAll("li"))).toEqual(["alpha", "beta"]);
  });

  it("treats -, * and + as the same kind of list", () => {
    const root = md("- dash\n* star\n+ plus");
    expect(root.querySelectorAll("ul")).toHaveLength(1);
    expect(root.querySelectorAll("li")).toHaveLength(3);
  });

  it("renders numbered lists as ordered", () => {
    const root = md("1. first\n2. second");
    expect(root.querySelectorAll("ol")).toHaveLength(1);
    expect(textOf(root.querySelectorAll("li"))).toEqual(["first", "second"]);
  });

  it("starts a new list when the marker kind changes", () => {
    const root = md("- bullet\n1. number");
    expect(root.querySelectorAll("ul")).toHaveLength(1);
    expect(root.querySelectorAll("ol")).toHaveLength(1);
  });

  it("continues a wrapped item instead of splitting it", () => {
    // Regression: models wrap constantly, and the first version turned every
    // continuation line into a stray paragraph, halving most bullets.
    const root = md("1. First attempt with defaults. F1 went\n   0.61 -> 0.64, so we moved on.");
    expect(textOf(root.querySelectorAll("li"))).toEqual([
      "First attempt with defaults. F1 went 0.61 -> 0.64, so we moved on.",
    ]);
    expect(root.querySelectorAll("p")).toHaveLength(0);
  });

  it("ends the list at a blank line", () => {
    const root = md("- item\n\nback to prose");
    expect(textOf(root.querySelectorAll("li"))).toEqual(["item"]);
    expect(textOf(root.querySelectorAll("p"))).toEqual(["back to prose"]);
  });
});

describe("inline markup", () => {
  it("renders bold, italic, and code spans", () => {
    const root = md("**bold** and *italic* and `code`");
    expect(textOf(root.querySelectorAll("strong"))).toEqual(["bold"]);
    expect(textOf(root.querySelectorAll("em"))).toEqual(["italic"]);
    expect(textOf(root.querySelectorAll("code"))).toEqual(["code"]);
  });

  it("supports underscore emphasis at word boundaries", () => {
    const root = md("__strong__ and _emphasis_");
    expect(textOf(root.querySelectorAll("strong"))).toEqual(["strong"]);
    expect(textOf(root.querySelectorAll("em"))).toEqual(["emphasis"]);
  });
});

describe("prose that only looks like markup", () => {
  // Every case here is a bug the browser fixtures caught before release.

  it("leaves lone asterisks alone", () => {
    const root = md("A literal asterisk * and another * later.");
    expect(root.querySelectorAll("em")).toHaveLength(0);
    expect(root.textContent).toBe("A literal asterisk * and another * later.");
  });

  it("does not read multiplication as emphasis", () => {
    const root = md("as should 2 * 3 * 4 = 24");
    expect(root.querySelectorAll("em")).toHaveLength(0);
    expect(root.textContent).toBe("as should 2 * 3 * 4 = 24");
  });

  // Two underscores is the case that matters: one alone has nothing to pair
  // with, so a single-underscore name would pass even against a broken rule.
  it.each([
    "my_var_name",
    "val_loss_history",
    "n_estimators_grid",
    "region_code_lookup",
  ])("leaves the identifier %s intact", (identifier) => {
    const root = md(`the column ${identifier} was dropped`);
    expect(root.querySelectorAll("em")).toHaveLength(0);
    expect(root.textContent).toContain(identifier);
  });

  it("leaves two separate single-underscore names alone", () => {
    // The pair that would otherwise open on one name and close on the next.
    const text = "we dropped region_code and kept val_loss";
    expect(md(text).querySelectorAll("em")).toHaveLength(0);
    expect(md(text).textContent).toBe(text);
  });

  it("leaves an unclosed bold marker as text", () => {
    const root = md("Unclosed **bold and nothing after");
    expect(root.querySelectorAll("strong")).toHaveLength(0);
    expect(root.textContent).toBe("Unclosed **bold and nothing after");
  });

  it("leaves an unclosed code span as text", () => {
    const root = md("Unclosed `code and nothing after");
    expect(root.querySelectorAll("code")).toHaveLength(0);
    expect(root.textContent).toBe("Unclosed `code and nothing after");
  });

  it("does not let emphasis swallow a whole sentence between two bare markers", () => {
    const text = "A * here and an underscore _ there, plus 2 * 3.";
    expect(md(text).textContent).toBe(text);
  });
});

describe("safety", () => {
  it("renders markup as text rather than as elements", () => {
    // The renderer builds React elements and never sets innerHTML, so
    // anything a model emits is inert.
    const root = md("<img src=x onerror=alert(1)> and <b>bold?</b>");
    expect(root.querySelectorAll("img")).toHaveLength(0);
    expect(root.querySelectorAll("b")).toHaveLength(0);
    expect(root.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("renders a script tag as literal text", () => {
    const root = md("```\n<script>alert(1)</script>\n```");
    expect(root.querySelectorAll("script")).toHaveLength(0);
    expect(root.querySelector("pre")!.textContent).toBe("<script>alert(1)</script>");
  });
});

describe("realistic answers", () => {
  it("handles a mixed answer end to end", () => {
    render(
      <Markdown
        text={[
          "You tried it twice.",
          "",
          "## What happened",
          "",
          "1. **First** — plain `SMOTE()`, F1 0.61 -> 0.64.",
          "2. **Second** — `k_neighbors=3`, which got 0.71.",
          "",
          "```python",
          "sm = SMOTE(k_neighbors=3)",
          "```",
        ].join("\n")}
      />,
    );
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("What happened");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("sm = SMOTE(k_neighbors=3)")).toBeTruthy();
  });

  it("renders an empty answer without crashing", () => {
    expect(md("").textContent).toBe("");
  });
});
