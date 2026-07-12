import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

type CloudWord = { x?: number; y?: number; rotate?: number; size?: number };
type CloudValue<T> = T | ((word: CloudWord, index: number) => T);

vi.mock("d3-cloud", () => ({
  default: () => {
    let words: CloudWord[] = [];
    let fontSize: CloudValue<number> = 16;
    let rotate: CloudValue<number> = 0;
    let onEnd: ((words: CloudWord[]) => void) | undefined;
    const layout = {
      size: () => layout,
      words: (nextWords: CloudWord[]) => { words = nextWords; return layout; },
      font: () => layout,
      fontWeight: () => layout,
      fontSize: (nextFontSize: CloudValue<number>) => { fontSize = nextFontSize; return layout; },
      padding: () => layout,
      rotate: (nextRotate: CloudValue<number>) => { rotate = nextRotate; return layout; },
      random: () => layout,
      on: (type: string, listener: (words: CloudWord[]) => void) => {
        if (type === "end") onEnd = listener;
        return layout;
      },
      start: () => {
        onEnd?.(words.map((word, index) => ({
          ...word,
          x: index * 36 - 70,
          y: (index % 3) * 30 - 30,
          rotate: typeof rotate === "function" ? rotate(word, index) : rotate,
          size: typeof fontSize === "function" ? fontSize(word, index) : fontSize,
        })));
        return layout;
      },
      stop: () => layout,
    };
    return layout;
  },
}));

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver ??= ResizeObserverMock;
Element.prototype.scrollTo ??= vi.fn();

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
