import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Decision = { id: string; statement: string; category: string; review_status: string; evidence_quote: string };
type Today = { intention: { statement?: string; status?: string; reason?: string }; memory: Decision[]; pending_decision: Decision | null };
type GitHubCredentials = { token_saved: boolean; webhook_secret_saved: boolean; state?: string };
type Evidence = { id: string; title: string; external_id: string; metadata: { commit?: string } };
const api = import.meta.env.VITE_FORGE_API ?? "";

function App() {
  const [today, setToday] = useState<Today | null>(null);
  const [intention, setIntention] = useState("");
  const [github, setGithub] = useState<GitHubCredentials | null>(null);
  const [token, setToken] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [editedStatement, setEditedStatement] = useState("");
  const load = () => fetch(`${api}/v1/workspaces/default/today`).then(response => response.json()).then(setToday);
  const loadGitHub = () => fetch(`${api}/v1/connectors/github`).then(response => response.json()).then(setGithub);
  const loadEvidence = () => fetch(`${api}/v1/workspaces/default/evidence`).then(response => response.json()).then(setEvidence);
  useEffect(() => { void load(); void loadGitHub(); void loadEvidence(); }, []);
  useEffect(() => { setEditedStatement(today?.pending_decision?.statement ?? ""); }, [today?.pending_decision?.id]);
  const review = async (id: string, status: "confirmed" | "rejected", statement?: string) => { await fetch(`${api}/v1/decisions/${id}/review`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ status, ...(statement && { statement }) }) }); load(); };
  const saveIntention = async (event: React.FormEvent) => { event.preventDefault(); if (!intention.trim()) return; await fetch(`${api}/v1/workspaces/default/intention`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ statement: intention }) }); setIntention(""); load(); };
  const saveGitHub = async (event: React.FormEvent) => { event.preventDefault(); const body = { ...(token && { token }), ...(webhookSecret && { webhook_secret: webhookSecret }) }; if (!Object.keys(body).length) return; await fetch(`${api}/v1/connectors/github`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }); setToken(""); setWebhookSecret(""); loadGitHub(); };
  const deleteGitHub = async () => { await fetch(`${api}/v1/connectors/github`, { method: "DELETE" }); loadGitHub(); };
  if (!today) return <main><p>Loading local memory…</p></main>;
  const pending = today.pending_decision;
  return <main>
    <header><p className="eyebrow">LOCAL-FIRST ENGINEERING MEMORY</p><h1>Today</h1><p>Forge stores Git evidence locally. Agents can propose; you decide.</p></header>
    <section><h2>Active intention</h2>{today.intention.statement ? <p className="intention">{today.intention.statement}</p> : <p className="muted">{today.intention.reason}</p>}<form onSubmit={saveIntention}><input aria-label="Active intention" value={intention} onChange={event => setIntention(event.target.value)} placeholder="e.g. Keep pull requests easy to review"/><button>Set intention</button></form></section>
    <section><h2>One memory</h2>{today.memory[0] ? <article><p>{today.memory[0].statement}</p><blockquote>{today.memory[0].evidence_quote}</blockquote></article> : <p className="muted">No confirmed memory yet.</p>}</section>
    <section><h2>Recent Git evidence</h2>{evidence.length ? <ul>{evidence.map(item => <li key={item.id}><code>{item.external_id.slice(0, 7)}</code> {item.title}</li>)}</ul> : <p className="muted">No Git evidence imported yet.</p>}</section>
    <section><h2>Review next</h2>{pending ? <article><small>{pending.category} · pending</small><textarea aria-label="Decision statement" value={editedStatement} onChange={event => setEditedStatement(event.target.value)}/><blockquote>{pending.evidence_quote}</blockquote><button onClick={() => review(pending.id, "confirmed", editedStatement)}>Confirm memory</button><button className="secondary" onClick={() => review(pending.id, "rejected")}>Dismiss</button></article> : <p className="muted">Nothing pending. Forge will not invent advice without cited evidence.</p>}</section>
    <section><h2>GitHub connector</h2><p className="muted">{github?.token_saved ? "Token saved" : "No token"} · {github?.webhook_secret_saved ? "Webhook secret saved" : "No webhook secret"}</p><form onSubmit={saveGitHub}><input type="password" aria-label="GitHub token" value={token} onChange={event => setToken(event.target.value)} placeholder="GitHub token"/><input type="password" aria-label="GitHub webhook secret" value={webhookSecret} onChange={event => setWebhookSecret(event.target.value)} placeholder="Webhook secret"/><button>Save update</button><button type="button" className="secondary" onClick={deleteGitHub}>Delete saved credentials</button></form><p className="muted">Saved with Windows account protection; Forge never displays them.</p></section>
    <footer>Forge never reads raw AI chat transcripts or edits <code>AGENTS.md</code> itself.</footer>
  </main>;
}
createRoot(document.getElementById("root")!).render(<App />);
