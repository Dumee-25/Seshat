/**
 * A deliberately small markdown renderer for chat answers.
 *
 * Local models emit headings, lists, code, and emphasis, and dropping that
 * into a plain <div> turns every answer into a wall. A full CommonMark
 * library is a large dependency for a frozen desktop bundle, and the cockpit
 * hand-rolls its components anyway, so this covers the subset models actually
 * produce and renders the rest as literal text.
 *
 * It builds React elements rather than HTML strings — there is no
 * dangerouslySetInnerHTML here, so nothing a model emits can inject markup.
 */
import type { JSX, ReactNode } from "react";

/**
 * One capturing group wrapping every alternative, so `split` yields
 * [text, marker, text, marker, …]. Two rules keep it from eating prose:
 *
 * - A delimiter must hug its content (`(?!\s)` / `(?<!\s)`), so the lone
 *   asterisks in "2 * 3 = 6" are not read as emphasis.
 * - `_` must not sit inside a word, so `region_code` and `k_neighbors` —
 *   which is most of what a research project talks about — stay literal.
 */
const INLINE = new RegExp(
  "(" +
    [
      "\\*\\*(?!\\s)[^\\n]+?(?<!\\s)\\*\\*", // **bold**
      "(?<!\\w)__(?!\\s)[^\\n]+?(?<!\\s)__(?!\\w)", // __bold__
      "\\*(?!\\s)[^*\\n]+?(?<!\\s)\\*", // *italic*
      "(?<!\\w)_(?!\\s)[^_\\n]+?(?<!\\s)_(?!\\w)", // _italic_
      "`[^`\\n]+?`", // `code`
    ].join("|") +
    ")",
  "g",
);

/** Bold, italic, and code spans. Unmatched markers stay as literal text. */
function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (i % 2 === 0) return part;
    if (part.startsWith("**") || part.startsWith("__")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`")) {
      return (
        <code key={i} className="md-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <em key={i}>{part.slice(1, -1)}</em>;
  });
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*(\d+)[.)]\s+(.*)$/;
const FENCE = /^\s*```/;

export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];

  // Buffers for the run of lines currently being accumulated.
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push(<p key={blocks.length}>{inline(paragraph.join(" "))}</p>);
    paragraph = [];
  };

  const flushList = () => {
    if (list === null) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    blocks.push(
      list.ordered ? (
        <ol key={blocks.length}>{items}</ol>
      ) : (
        <ul key={blocks.length}>{items}</ul>
      ),
    );
    list = null;
  };

  const flush = () => {
    flushParagraph();
    flushList();
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (FENCE.test(line)) {
      flush();
      const body: string[] = [];
      i++; // step past the opening fence
      while (i < lines.length && !FENCE.test(lines[i])) body.push(lines[i++]);
      // An unterminated fence runs to the end of the message rather than
      // swallowing the block — a truncated answer still shows its code.
      blocks.push(
        <pre key={blocks.length} className="md-pre">
          {body.join("\n")}
        </pre>,
      );
      continue;
    }

    if (line.trim() === "") {
      flush();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      const level = Math.min(heading[1].length, 6);
      const Tag = `h${level}` as keyof JSX.IntrinsicElements;
      blocks.push(
        <Tag key={blocks.length} className="md-h">
          {inline(heading[2])}
        </Tag>,
      );
      continue;
    }

    const numbered = NUMBERED.exec(line);
    const bullet = BULLET.exec(line);
    if (numbered || bullet) {
      flushParagraph();
      const ordered = numbered !== null;
      const item = numbered ? numbered[2] : bullet![1];
      // A switch between bullets and numbers starts a new list.
      if (list === null || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push(item);
      continue;
    }

    // Lazy continuation: a wrapped list item is still that item, not a new
    // paragraph. Models wrap constantly, so without this every long bullet
    // splits in half.
    if (list !== null) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
      continue;
    }

    paragraph.push(line);
  }

  flush();
  return <div className="md">{blocks}</div>;
}
