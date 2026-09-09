import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import ChannelComposer from "../src/ChannelComposer";
import "../src/app.css";

const members = [
  { principal_id: "admin-agent", display_name: "平台管理 Agent", principal_type: "AGENT" },
  { principal_id: "sam-1", display_name: "Sam", principal_type: "HUMAN" },
  { principal_id: "sam-2", display_name: "Sam", principal_type: "HUMAN" },
  { principal_id: "hermes", display_name: "Hermes Agent", principal_type: "AGENT" },
];
const commands = [
  {command_key:"HEALTH_READ", risk_level:"LOW", execution_mode:"DIRECT_READ", example:"/platform HEALTH_READ", metadata:{name_zh:"平台健康",name_en:"Platform health"}},
  {command_key:"AGENT_DRAIN", risk_level:"HIGH", execution_mode:"GOVERNED_EXECUTOR", example:"/platform AGENT_DRAIN <source> <destination> [reason]", metadata:{name_zh:"节点排空",name_en:"Drain node"}},
];
function Preview() {
  const [body, setBody] = useState("");
  const [threadId, setThreadId] = useState("");
  const [messages, setMessages] = useState<any[]>([]);
  const [sending, setSending] = useState(false);
  return <main style={{maxWidth:960,margin:"24px auto",padding:12}}>
    <h1 style={{fontSize:22}}>管理频道 · v4.4.13 交互预览</h1>
    <p>测试数据，消息仅保存在当前浏览器页面。</p>
    <div className="message-stream" style={{height:320}}>{messages.map((item,i)=><article key={i} className="channel-message"><div className="channel-message-body"><b>当前用户</b><p>{item.body}</p><small>{item.mentions.join(", ")}</small></div></article>)}</div>
    <ChannelComposer body={body} setBody={setBody} members={members} commands={commands} threads={[]} threadId={threadId} setThreadId={setThreadId} sending={sending} feedback="" lang="zh" text={(zh)=>zh} onSend={async (mentions)=>{
      setSending(true); setMessages((items)=>[...items,{body,mentions}]); setBody(""); setSending(false);
    }} />
    <output id="sent-count" hidden>{messages.length}</output>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Preview />);
