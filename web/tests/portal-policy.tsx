import React from "react";
import { createRoot } from "react-dom/client";
import PortalKnowledgePolicy from "../src/PortalKnowledgePolicy";
import "../src/app.css";

const english = new URLSearchParams(location.search).get("lang") === "en";
createRoot(document.getElementById("root")!).render(<main style={{ maxWidth: 960, margin: "24px auto", padding: 12 }}>
  <PortalKnowledgePolicy text={(zh, en) => english ? en : zh} request={async (path, options) => {
    const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json" } });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail);
    return body;
  }} />
</main>);
