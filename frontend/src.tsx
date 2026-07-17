import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Decision = { id: string; statement: string; review_status: string; evidence_quote: string };
const api = import.meta.env.VITE_FORGE_API ?? "http://localhost:8000";

function App() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const load = () => fetch(`${api}/v1/workspaces/default/decisions`).then(r => r.json()).then(setDecisions);
  useEffect(() => { void load(); }, []);
  const review = async (id: string, status: string) => { await fetch(`${api}/v1/decisions/${id}/review`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ status }) }); load(); };
  return <main><h1>Forge</h1><p>Evidence-backed engineering memory.</p>{decisions.map(d => <article key={d.id}><small>{d.review_status}</small><h2>{d.statement}</h2><p>Evidence: “{d.evidence_quote}”</p>{d.review_status === "pending" && <><button onClick={() => review(d.id, "confirmed")}>Confirm</button><button onClick={() => review(d.id, "rejected")}>Reject</button></>}</article>)}</main>;
}
createRoot(document.getElementById("root")!).render(<App />);
