import React, { useEffect, useRef, useState } from "react";
import { AtSign, Slash, Send } from "lucide-react";
import { commandQuery, hasCommandPlaceholders, mentionQuery, rebaseMentions, selectedMentionIds } from "./channelCompletion";
import type { Mention } from "./channelCompletion";

type Row = Record<string, any>;
type Props = {
  body: string; setBody: (body: string) => void; members: Row[]; commands: Row[];
  threads: Row[]; threadId: string; setThreadId: (id: string) => void;
  sending: boolean; feedback: string; lang: "zh" | "en";
  text: (zh: string, en: string) => string;
  onSend: (mentions: string[]) => Promise<void>;
};

export default function ChannelComposer(props: Props) {
  const { body, setBody, members, commands, text } = props;
  const input = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const [caret, setCaret] = useState(body.length);
  const [bindings, setBindings] = useState<{ body: string; mentions: Mention[] }>({ body, mentions: [] });
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState("");
  const mentions = rebaseMentions(bindings.body, body, bindings.mentions);
  const possibleMention = mentionQuery(body, caret);
  const mention = possibleMention && !mentions.some((item) => item.start === possibleMention.start && caret > item.end) ? possibleMention : null;
  const query = commandQuery(body);
  const mentionItems = mention ? members.filter((item) =>
    `${item.display_name || ""} ${item.principal_id}`.toLowerCase().includes(mention.query)).slice(0, 8) : [];
  const commandItems = query !== null ? commands.filter((item) =>
    `${item.command_key} ${item.metadata?.name_zh || ""} ${item.metadata?.name_en || ""} ${item.metadata?.summary_zh || ""}`.toLowerCase().includes(query)).slice(0, 10) : [];
  const items = dismissed ? [] : mention ? mentionItems : commandItems;
  const index = Math.min(active, Math.max(items.length - 1, 0));
  useEffect(() => {
    document.getElementById(`channel-completion-${index}`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [index, body, dismissed]);
  const update = (next: string, position: number, nextMentions = rebaseMentions(body, next, mentions)) => {
    setBindings({ body: next, mentions: nextMentions });
    setBody(next); setCaret(position); setActive(0); setDismissed(false); setError("");
  };
  const focus = (position: number) => requestAnimationFrame(() => {
    input.current?.focus(); input.current?.setSelectionRange(position, position);
  });
  const pick = (item: Row) => {
    if (mention) {
      const label = `@${String(item.display_name || item.principal_id).trim()}`;
      const next = body.slice(0, mention.start) + label + " " + body.slice(mention.end);
      const position = mention.start + label.length + 1;
      update(next, position, [...rebaseMentions(body, next, mentions), { start: mention.start, end: position - 1, label, principalId: String(item.principal_id) }]);
      setDismissed(true); focus(position);
    } else {
      const next = String(item.example || `/platform ${item.command_key}`).trimEnd() + " ";
      update(next, next.length); setDismissed(true); focus(next.length);
      const placeholder = next.match(/<[^>]+>|\[reason\]/i);
      if (placeholder) requestAnimationFrame(() => input.current?.setSelectionRange(placeholder.index!, placeholder.index! + placeholder[0].length));
    }
  };
  const submit = async () => {
    if (props.sending || composing.current || !body.trim()) return;
    if (hasCommandPlaceholders(body)) { setError(text("请填写命令中的参数和原因。", "Complete the command parameters and reason.")); return; }
    await props.onSend(selectedMentionIds(body, mentions, new Set(members.map((item) => String(item.principal_id)))));
  };
  const insertTrigger = (trigger: string) => {
    const position = input.current?.selectionStart ?? body.length;
    const prefix = position && !/\s/.test(body[position - 1]) ? " " : "";
    const next = trigger === "/" && !body.trim() ? "/" : body.slice(0, position) + prefix + trigger + body.slice(position);
    const nextCaret = trigger === "/" && !body.trim() ? 1 : position + prefix.length + trigger.length;
    update(next, nextCaret); focus(nextCaret);
  };
  return <form className="message-compose" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    <div className="channel-composer-input">
      {items.length > 0 && <div id="channel-completions" className="mention-menu channel-completions" role="listbox" aria-label={mention ? text("频道成员", "Channel members") : text("平台命令", "Platform commands")}>
        {items.map((item, i) => <button id={`channel-completion-${i}`} key={String(mention ? item.principal_id : item.command_key)} type="button" role="option" aria-selected={i === index} onMouseDown={(event) => event.preventDefault()} onClick={() => pick(item)}>
          <span><b>{mention ? item.display_name || item.principal_id : `/platform ${item.command_key}`}</b><small>{mention ? item.principal_id : item.metadata?.[props.lang === "zh" ? "name_zh" : "name_en"]}</small></span>
          <small>{mention ? item.principal_type : `${item.risk_level} · ${item.execution_mode}`}</small>
        </button>)}
      </div>}
      <textarea ref={input} aria-label={text("消息内容", "Message")} aria-autocomplete="list" aria-controls={items.length ? "channel-completions" : undefined} aria-activedescendant={items.length ? `channel-completion-${index}` : undefined}
        value={body} onChange={(event) => update(event.target.value, event.target.selectionStart)}
        onSelect={(event) => { setCaret(event.currentTarget.selectionStart); }}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(event) => {
          if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
          if (event.key === "Escape") { event.preventDefault(); setDismissed(true); return; }
          if (items.length && ["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); setActive((index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length); return; }
          if (items.length && (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey))) { event.preventDefault(); pick(items[index]); return; }
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); }
        }} />
      {(error || props.feedback) && <small className="operation-feedback" role="status">{error || props.feedback}</small>}
      {!dismissed && mention && !mentionItems.length && <small role="status">{text("没有匹配的频道成员", "No matching channel members")}</small>}
    </div>
    <div className="compose-controls">
      <button type="button" className="icon-button" title={text("提及成员", "Mention member")} onClick={() => insertTrigger("@")}><AtSign size={17} /></button>
      {commands.length > 0 && <button type="button" className="icon-button" disabled={Boolean(body.trim())} title={text("平台命令", "Platform commands")} onClick={() => insertTrigger("/")}><Slash size={17} /></button>}
      <select aria-label={text("消息线程", "Message thread")} value={props.threadId} onChange={(event) => props.setThreadId(event.target.value)}><option value="">{text("频道消息", "Channel message")}</option>{props.threads.map((item) => <option key={item.thread_id} value={item.thread_id}>{item.thread_type} · {item.thread_id}</option>)}</select>
      <button className="primary-button" disabled={!body.trim() || props.sending}><Send size={16} />{props.sending ? text("发送中", "Sending") : text("发送", "Send")}</button>
    </div>
  </form>;
}
