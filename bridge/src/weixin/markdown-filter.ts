/**
 * Streaming markdown filter adapted from official openclaw-weixin 2.1.7.
 *
 * Our bridge sends the final text in a single shot, but keeping the same
 * state-machine shape makes it easier to stay aligned with upstream fixes.
 */
export class StreamingMarkdownFilter {
  private buf = "";
  private fence = false;
  private sol = true;
  private inl:
    | {
      type: "code" | "image" | "strike" | "bold3" | "italic" | "ubold3" | "uitalic" | "table";
      acc: string;
    }
    | null = null;

  feed(delta: string): string {
    this.buf += delta;
    return this.pump(false);
  }

  flush(): string {
    return this.pump(true);
  }

  private pump(eof: boolean): string {
    let out = "";
    while (this.buf) {
      const sLen = this.buf.length;
      const sSol = this.sol;
      const sFence = this.fence;
      const sInl = this.inl;

      if (this.fence) out += this.pumpFence(eof);
      else if (this.inl) out += this.pumpInline(eof);
      else if (this.sol) out += this.pumpSOL(eof);
      else out += this.pumpBody(eof);

      if (this.buf.length === sLen && this.sol === sSol && this.fence === sFence && this.inl === sInl) {
        break;
      }
    }

    if (eof && this.inl) {
      if (this.inl.type === "table") {
        out += StreamingMarkdownFilter.extractTableRow(this.inl.acc);
      } else {
        const markers: Record<string, string> = {
          code: "`",
          image: "![",
          strike: "~~",
          bold3: "***",
          italic: "*",
          ubold3: "___",
          uitalic: "_",
          table: "",
        };
        out += (markers[this.inl.type] ?? "") + this.inl.acc;
      }
      this.inl = null;
    }
    return out;
  }

  private pumpFence(eof: boolean): string {
    if (this.sol) {
      if (this.buf.length < 3 && !eof) return "";
      if (this.buf.startsWith("```")) {
        this.fence = false;
        const nl = this.buf.indexOf("\n", 3);
        this.buf = nl !== -1 ? this.buf.slice(nl + 1) : "";
        this.sol = true;
        return "";
      }
      this.sol = false;
    }
    const nl = this.buf.indexOf("\n");
    if (nl !== -1) {
      const chunk = this.buf.slice(0, nl + 1);
      this.buf = this.buf.slice(nl + 1);
      this.sol = true;
      return chunk;
    }
    const chunk = this.buf;
    this.buf = "";
    return chunk;
  }

  private pumpSOL(eof: boolean): string {
    const b = this.buf;

    if (b[0] === "\n") {
      this.buf = b.slice(1);
      return "\n";
    }

    if (b[0] === "`") {
      if (b.length < 3 && !eof) return "";
      if (b.startsWith("```")) {
        this.fence = true;
        const nl = b.indexOf("\n", 3);
        this.buf = nl !== -1 ? b.slice(nl + 1) : "";
        this.sol = true;
        return "";
      }
      this.sol = false;
      return "";
    }

    if (b[0] === ">") {
      if (b.length < 2 && !eof) return "";
      this.buf = b.length >= 2 && b[1] === " " ? b.slice(2) : b.slice(1);
      this.sol = false;
      return "";
    }

    if (b[0] === "#") {
      let n = 0;
      while (n < b.length && b[n] === "#") n++;
      if (n === b.length && !eof) return "";
      if (n >= 5 && n <= 6 && n < b.length && b[n] === " ") {
        this.buf = b.slice(n + 1);
        this.sol = false;
        return "";
      }
      this.sol = false;
      return "";
    }

    if (b[0] === "|") {
      this.buf = b.slice(1);
      this.inl = { type: "table", acc: "" };
      this.sol = false;
      return "";
    }

    if (b[0] === " " || b[0] === "\t") {
      if (b.search(/[^ \t]/) === -1 && !eof) return "";
      this.sol = false;
      return "";
    }

    if (b[0] === "-" || b[0] === "*" || b[0] === "_") {
      const ch = b[0];
      let j = 0;
      while (j < b.length && (b[j] === ch || b[j] === " ")) j++;
      if (j === b.length && !eof) return "";
      if (j === b.length || b[j] === "\n") {
        let count = 0;
        for (let k = 0; k < j; k++) {
          if (b[k] === ch) count++;
        }
        if (count >= 3) {
          this.buf = j < b.length ? b.slice(j + 1) : "";
          this.sol = true;
          return "";
        }
      }
      this.sol = false;
      return "";
    }

    this.sol = false;
    return "";
  }

  private pumpBody(eof: boolean): string {
    let out = "";
    let i = 0;
    while (i < this.buf.length) {
      const c = this.buf[i];
      if (c === "\n") {
        out += this.buf.slice(0, i + 1);
        this.buf = this.buf.slice(i + 1);
        this.sol = true;
        return out;
      }
      if (c === "`") {
        out += this.buf.slice(0, i);
        this.buf = this.buf.slice(i + 1);
        this.inl = { type: "code", acc: "" };
        return out;
      }
      if (c === "!" && i + 1 < this.buf.length && this.buf[i + 1] === "[") {
        out += this.buf.slice(0, i);
        this.buf = this.buf.slice(i + 2);
        this.inl = { type: "image", acc: "" };
        return out;
      }
      if (c === "~" && i + 1 < this.buf.length && this.buf[i + 1] === "~") {
        out += this.buf.slice(0, i);
        this.buf = this.buf.slice(i + 2);
        this.inl = { type: "strike", acc: "" };
        return out;
      }
      if (c === "*") {
        if (i + 2 < this.buf.length && this.buf[i + 1] === "*" && this.buf[i + 2] === "*") {
          out += this.buf.slice(0, i);
          this.buf = this.buf.slice(i + 3);
          this.inl = { type: "bold3", acc: "" };
          return out;
        }
        if (i + 1 < this.buf.length && this.buf[i + 1] === "*") {
          i += 2;
          continue;
        }
        if (i + 1 < this.buf.length && this.buf[i + 1] !== " " && this.buf[i + 1] !== "\n") {
          out += this.buf.slice(0, i);
          this.buf = this.buf.slice(i + 1);
          this.inl = { type: "italic", acc: "" };
          return out;
        }
        i++;
        continue;
      }
      if (c === "_") {
        if (i + 2 < this.buf.length && this.buf[i + 1] === "_" && this.buf[i + 2] === "_") {
          out += this.buf.slice(0, i);
          this.buf = this.buf.slice(i + 3);
          this.inl = { type: "ubold3", acc: "" };
          return out;
        }
        if (i + 1 < this.buf.length && this.buf[i + 1] === "_") {
          i += 2;
          continue;
        }
        if (i + 1 < this.buf.length && this.buf[i + 1] !== " " && this.buf[i + 1] !== "\n") {
          out += this.buf.slice(0, i);
          this.buf = this.buf.slice(i + 1);
          this.inl = { type: "uitalic", acc: "" };
          return out;
        }
        i++;
        continue;
      }
      i++;
    }

    let hold = 0;
    if (!eof) {
      if (this.buf.endsWith("**") || this.buf.endsWith("__")) hold = 2;
      else if (this.buf.endsWith("*") || this.buf.endsWith("_") || this.buf.endsWith("~") || this.buf.endsWith("!")) hold = 1;
    }
    out += this.buf.slice(0, this.buf.length - hold);
    this.buf = hold > 0 ? this.buf.slice(-hold) : "";
    return out;
  }

  private pumpInline(_eof: boolean): string {
    if (!this.inl) return "";
    this.inl.acc += this.buf;
    this.buf = "";

    switch (this.inl.type) {
      case "code": {
        const idx = this.inl.acc.indexOf("`");
        if (idx !== -1) {
          const content = this.inl.acc.slice(0, idx);
          this.buf = this.inl.acc.slice(idx + 1);
          this.inl = null;
          return content;
        }
        return "";
      }
      case "image": {
        const idx = this.inl.acc.indexOf(")");
        if (idx !== -1) {
          const whole = this.inl.acc.slice(0, idx + 1);
          this.buf = this.inl.acc.slice(idx + 1);
          this.inl = null;
          const closeBracket = whole.indexOf("]");
          if (closeBracket !== -1) {
            return whole.slice(0, closeBracket).replace(/^\[/, "");
          }
          return whole;
        }
        return "";
      }
      case "table": {
        const idx = this.inl.acc.indexOf("\n");
        if (idx !== -1) {
          const row = this.inl.acc.slice(0, idx);
          this.buf = this.inl.acc.slice(idx + 1);
          this.inl = null;
          this.sol = true;
          return StreamingMarkdownFilter.extractTableRow(row) + "\n";
        }
        return "";
      }
      default: {
        const marker = {
          strike: "~~",
          bold3: "***",
          italic: "*",
          ubold3: "___",
          uitalic: "_",
        }[this.inl.type];
        const idx = this.inl.acc.indexOf(marker);
        if (idx !== -1) {
          const content = this.inl.acc.slice(0, idx);
          this.buf = this.inl.acc.slice(idx + marker.length);
          this.inl = null;
          return content;
        }
        return "";
      }
    }
  }

  private static extractTableRow(row: string): string {
    return row
      .split("|")
      .map((cell) => cell.trim())
      .filter(Boolean)
      .join(" | ");
  }
}

export function filterWeixinMarkdown(text: string): string {
  const filter = new StreamingMarkdownFilter();
  return filter.feed(text || "") + filter.flush();
}
