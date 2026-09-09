export type Mention = { start: number; end: number; label: string; principalId: string };

export function mentionQuery(body: string, caret: number) {
  const match = body.slice(0, caret).match(/(?:^|\s)@([^@\n]*)$/);
  return match ? { start: caret - match[1].length - 1, end: caret, query: match[1].toLowerCase() } : null;
}

export function commandQuery(body: string): string | null {
  if (/^\/(?:p(?:l(?:a(?:t(?:f(?:o(?:r(?:m)?)?)?)?)?)?)?)?$/i.test(body)) return "";
  const match = body.match(/^\/platform\s+([^\s]*)$/i);
  return match ? match[1].toLowerCase() : null;
}

// Keep identity bindings only for untouched spans; retyping a name cannot
// silently transfer a selected mention to a different principal.
export function rebaseMentions(previous: string, next: string, mentions: Mention[]): Mention[] {
  let start = 0;
  while (start < previous.length && start < next.length && previous[start] === next[start]) start++;
  let oldEnd = previous.length, newEnd = next.length;
  while (oldEnd > start && newEnd > start && previous[oldEnd - 1] === next[newEnd - 1]) { oldEnd--; newEnd--; }
  if (previous.length !== next.length) {
    let suffix = 0;
    while (suffix < Math.min(previous.length, next.length) && previous[previous.length - suffix - 1] === next[next.length - suffix - 1]) suffix++;
    // Repeated identical names make a text-only edit ambiguous. Drop all
    // affected bindings instead of retaining the wrong member's identity.
    if (start + suffix > Math.min(previous.length, next.length)) {
      oldEnd = Math.max(start, previous.length - suffix);
      newEnd = Math.max(start, next.length - suffix);
      start = Math.min(start, previous.length - suffix, next.length - suffix);
    }
  }
  return mentions.flatMap((item) => {
    if (item.end <= start) return [item];
    if (item.start >= oldEnd) return [{ ...item, start: item.start + newEnd - oldEnd, end: item.end + newEnd - oldEnd }];
    return [];
  }).filter((item) => next.slice(item.start, item.end) === item.label
    && (item.start === 0 || /\s/.test(next[item.start - 1]))
    && (item.end === next.length || /\s|[,.!?;:，。！？；：]/u.test(next[item.end])));
}

export function selectedMentionIds(body: string, mentions: Mention[], memberIds: Set<string>): string[] {
  return [...new Set(rebaseMentions(body, body, mentions)
    .filter((item) => memberIds.has(item.principalId)).map((item) => item.principalId))];
}

export function hasCommandPlaceholders(body: string): boolean {
  return /^\/platform\s/i.test(body) && /<[^>\n]+>|\[(?:reason|原因)\]/i.test(body);
}
