/**
 * Pipeline nodes on the clipboard. X5 of `GOAL_GRAPH_2026-09-23.md`.
 *
 * A copy is the selected nodes and the edges between them, as JSON. It goes to the
 * system clipboard twice -- under a private format that only this product reads, and
 * as plain text a person can see -- so a copy made in one pipeline pastes into
 * another, in this tab or another one. The payload names its own kind, so a paste
 * reads it rather than guessing at whatever text happens to be on the clipboard.
 *
 * The system clipboard can refuse: no permission, no focus, a browser without custom
 * formats. The last copy is also kept in this tab, and a paste that cannot read the
 * system clipboard uses it, and says so.
 */

export const CLIPBOARD_KIND = "ontology-platform/pipeline-nodes";
export const CLIPBOARD_FORMAT = "web application/x-ontology-pipeline-nodes+json";

export interface CopiedNodes {
  kind: typeof CLIPBOARD_KIND;
  version: 1;
  nodes: Array<{
    id: string;
    type: string;
    label: string;
    config: Record<string, unknown>;
    position: { x: number; y: number };
  }>;
  edges: Array<{ source: string; target: string }>;
}

let heldInTab: CopiedNodes | null = null;

function parse(text: string): CopiedNodes | null {
  try {
    const value = JSON.parse(text);
    return value?.kind === CLIPBOARD_KIND && Array.isArray(value.nodes) && Array.isArray(value.edges) ? value : null;
  } catch {
    return null;
  }
}

/** Where a copy went: the system clipboard, or only this tab. */
export async function writeNodes(copied: CopiedNodes): Promise<"system" | "tab"> {
  heldInTab = copied;
  const text = JSON.stringify(copied);
  try {
    if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
      await navigator.clipboard.write([new ClipboardItem({
        "text/plain": new Blob([text], { type: "text/plain" }),
        [CLIPBOARD_FORMAT]: new Blob([text], { type: CLIPBOARD_FORMAT }),
      })]);
      return "system";
    }
  } catch {
    /* a custom format refused, or no permission: try plain text next */
  }
  try {
    await navigator.clipboard.writeText(text);
    return "system";
  } catch {
    return "tab";
  }
}

/**
 * The nodes on the clipboard, and where they were read from. A clipboard that was
 * read and holds something else has nothing to paste: something copied after these
 * nodes replaced them. The tab's own copy is for a clipboard that could not be read.
 */
export async function readNodes(): Promise<{ copied: CopiedNodes; from: "system" | "tab" } | null> {
  let readable = false;
  try {
    for (const item of await navigator.clipboard.read()) {
      readable = true;
      for (const type of [CLIPBOARD_FORMAT, "text/plain"]) {
        if (!item.types.includes(type)) continue;
        const copied = parse(await (await item.getType(type)).text());
        if (copied) return { copied, from: "system" };
      }
    }
  } catch {
    /* no permission to read items: try the text below */
  }
  try {
    const text = await navigator.clipboard.readText();
    readable = true;
    const copied = parse(text);
    if (copied) return { copied, from: "system" };
  } catch {
    /* no permission to read at all */
  }
  if (readable) return null;
  return heldInTab ? { copied: heldInTab, from: "tab" } : null;
}
