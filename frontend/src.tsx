import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Decision = { id: string; statement: string; category: string; review_status: string; evidence_quote: string };
type Reflection = { id: string; statement: string; evidence_quote: string; review_status: string };
type Today = { intention: { statement?: string; status?: string; reason?: string }; memory: (Decision & { memory_entry_id: string })[]; pending_decision: Decision | null; pending_reflection: Reflection | null };
type GitHubCredentials = { token_saved: boolean; state: string; detail?: string };
type Evidence = { id: string; title: string; external_id: string; metadata: { commit?: string } };
type EvidenceDetail = Evidence & { content: string; metadata: { commit?: string; author?: string; occurred_at?: string; files?: string[] }; spans: { id: string; quote: string }[] };
type Repository = { path: string; remote_url?: string; branch?: string; last_ingested_commit?: string };
type RegisteredRepository = Repository & { workspace_id: string };
type History = { decisions: Decision[]; reflections: Reflection[] };
const api = import.meta.env.VITE_FORGE_API ?? "";

function App() {
  const [today, setToday] = useState<Today | null>(null);
  const [intention, setIntention] = useState("");
  const [github, setGithub] = useState<GitHubCredentials | null>(null);
  const [token, setToken] = useState("");
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [githubEvidence, setGithubEvidence] = useState<Evidence[]>([]);
  const [githubReviews, setGithubReviews] = useState<Evidence[]>([]);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceDetail | null>(null);
  const [editedStatement, setEditedStatement] = useState("");
  const [repository, setRepository] = useState<Repository | null>(null);
  const [repositories, setRepositories] = useState<RegisteredRepository[]>([]);
  const [workspace, setWorkspace] = useState("default");
  const [repositoryPath, setRepositoryPath] = useState("");
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState("");
  const load = () => fetch(`${api}/v1/workspaces/${workspace}/today`).then(response => { if (!response.ok) throw new Error("Forge is offline or could not load Today."); return response.json(); }).then(setToday).catch(loadError => setError(loadError.message));
  const loadGitHub = () => fetch(`${api}/v1/connectors/github`).then(response => response.json()).then(setGithub);
  const loadEvidence = () => fetch(`${api}/v1/workspaces/${workspace}/evidence`).then(response => response.json()).then(setEvidence);
  const loadGitHubEvidence = () => fetch(`${api}/v1/workspaces/${workspace}/evidence?kind=github_pull_request`).then(response => response.json()).then(setGithubEvidence);
  const loadGitHubReviews = () => fetch(`${api}/v1/workspaces/${workspace}/evidence?kind=github_review`).then(response => response.json()).then(setGithubReviews);
  const loadRepository = () => fetch(`${api}/v1/workspaces/${workspace}/repository`).then(response => response.ok ? response.json() : null).then(setRepository);
  const loadHistory = () => fetch(`${api}/v1/workspaces/${workspace}/history`).then(response => response.json()).then(setHistory);
  const loadRepositories = () => fetch(`${api}/v1/repositories`).then(response => response.json()).then(setRepositories);
  useEffect(() => { void loadGitHub(); void loadRepositories(); }, []);
  useEffect(() => { void load(); void loadEvidence(); void loadGitHubEvidence(); void loadGitHubReviews(); void loadRepository(); void loadHistory(); }, [workspace]);
  useEffect(() => { setEditedStatement(today?.pending_decision?.statement ?? ""); }, [today?.pending_decision?.id]);
  const review = async (id: string, status: "confirmed" | "rejected", statement?: string) => { await fetch(`${api}/v1/decisions/${id}/review`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ status, ...(statement && { statement }) }) }); load(); };
  const saveIntention = async (event: React.FormEvent) => { event.preventDefault(); if (!intention.trim()) return; await fetch(`${api}/v1/workspaces/${workspace}/intention`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ statement: intention }) }); setIntention(""); load(); };
  const saveGitHub = async (event: React.FormEvent) => { event.preventDefault(); if (!token) return; await fetch(`${api}/v1/connectors/github`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ token }) }); setToken(""); loadGitHub(); };
  const deleteGitHub = async () => { await fetch(`${api}/v1/connectors/github`, { method: "DELETE" }); loadGitHub(); };
  const pollGitHub = async () => { const response = await fetch(`${api}/v1/workspaces/${workspace}/github/poll`, { method: "POST" }); if (!response.ok) setError((await response.json()).detail || "GitHub polling failed."); loadGitHub(); loadGitHubEvidence(); loadGitHubReviews(); };
  const showEvidence = async (id: string) => setSelectedEvidence(await fetch(`${api}/v1/evidence/${id}`).then(response => response.json()));
  const archiveMemory = async (entryId: string) => { await fetch(`${api}/v1/memory/${entryId}/archive`, { method: "POST" }); load(); };
  const reviewReflection = async (id: string, status: "confirmed" | "dismissed") => { await fetch(`${api}/v1/reflections/${id}/review`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ status }) }); load(); };
  const refreshEvidence = async () => { if (!repository) return; await fetch(`${api}/v1/workspaces/${workspace}/git/imports`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ path: repository.path }) }); loadEvidence(); loadRepository(); };
  const addRepository = async (event: React.FormEvent) => { event.preventDefault(); if (!repositoryPath.trim()) return; const response = await fetch(`${api}/v1/repositories`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ path: repositoryPath }) }); if (!response.ok) { setError((await response.json()).detail || "Could not register repository."); return; } const result = await response.json(); setRepositoryPath(""); await loadRepositories(); setWorkspace(result.workspace_id); };
  if (error) return <main><h1>Forge is offline</h1><p>{error}</p><button onClick={() => { setError(""); load(); }}>Retry</button></main>;
  if (!today) return <main><p>Loading local memory…</p></main>;
  const pending = today.pending_decision;
  return <main>
    <header><p className="eyebrow">LOCAL-FIRST ENGINEERING MEMORY</p><h1>Today</h1><p>Forge stores Git evidence locally. Agents can propose; you decide.</p></header>
    <section><h2>Repository</h2><label className="muted" htmlFor="repository-select">Active project</label><select id="repository-select" value={workspace} onChange={event => setWorkspace(event.target.value)}>{repository && !repositories.some(item => item.workspace_id === workspace) && <option value={workspace}>{repository.path}</option>}{repositories.map(item => <option key={item.workspace_id} value={item.workspace_id}>{item.path}</option>)}</select>{repository ? <><p><code>{repository.path}</code></p><p className="muted">{repository.branch} · {repository.remote_url || "no remote"}</p><button onClick={refreshEvidence}>Refresh Git evidence</button></> : <p className="muted">No repository registered yet.</p>}<form onSubmit={addRepository}><input aria-label="Repository path" value={repositoryPath} onChange={event => setRepositoryPath(event.target.value)} placeholder="Add a local Git repository path"/><button>Add repository</button></form></section>
    <section><h2>Active intention</h2>{today.intention.statement ? <p className="intention">{today.intention.statement}</p> : <p className="muted">{today.intention.reason}</p>}<form onSubmit={saveIntention}><input aria-label="Active intention" value={intention} onChange={event => setIntention(event.target.value)} placeholder="e.g. Keep pull requests easy to review"/><button>Set intention</button></form></section>
    <section><h2>One memory</h2>{today.memory[0] ? <article><p>{today.memory[0].statement}</p><blockquote>{today.memory[0].evidence_quote}</blockquote><button className="secondary" onClick={() => archiveMemory(today.memory[0].memory_entry_id)}>Archive memory</button></article> : <p className="muted">No confirmed memory yet.</p>}</section>
    <section><h2>Recent Git evidence</h2>{evidence.length ? <ul>{evidence.map(item => <li key={item.id}><button className="link" onClick={() => showEvidence(item.id)}><code>{item.external_id.slice(0, 7)}</code> {item.title}</button></li>)}</ul> : <p className="muted">No Git evidence imported yet.</p>}{selectedEvidence && <article><small>{selectedEvidence.metadata.author} · {selectedEvidence.metadata.occurred_at}</small><h3>{selectedEvidence.title}</h3><p>{selectedEvidence.metadata.files?.join(", ") || "No changed files"}</p><blockquote>{selectedEvidence.spans.map(span => span.quote).join("\n")}</blockquote><details><summary>View local diff</summary><pre>{selectedEvidence.content}</pre></details></article>}</section>
    <section><h2>GitHub evidence</h2>{githubEvidence.length || githubReviews.length ? <><h3>Pull requests</h3>{githubEvidence.length ? <ul>{githubEvidence.map(item => <li key={item.id}><button className="link" onClick={() => showEvidence(item.id)}>{item.title}</button></li>)}</ul> : <p className="muted">No pull requests imported yet.</p>}<h3>Reviews</h3>{githubReviews.length ? <ul>{githubReviews.map(item => <li key={item.id}><button className="link" onClick={() => showEvidence(item.id)}>{item.title}</button></li>)}</ul> : <p className="muted">No reviews imported yet.</p>}</> : <p className="muted">No pull requests or reviews imported yet.</p>}</section>
    <section><h2>Review next</h2>{pending ? <article><small>{pending.category} · pending</small><textarea aria-label="Decision statement" value={editedStatement} onChange={event => setEditedStatement(event.target.value)}/><blockquote>{pending.evidence_quote}</blockquote><button onClick={() => review(pending.id, "confirmed", editedStatement)}>Confirm memory</button><button className="secondary" onClick={() => review(pending.id, "rejected")}>Dismiss</button></article> : <p className="muted">Nothing pending. Forge will not invent advice without cited evidence.</p>}</section>
    <section><h2>Reflection</h2>{today.pending_reflection ? <article><p>{today.pending_reflection.statement}</p><blockquote>{today.pending_reflection.evidence_quote}</blockquote><button onClick={() => reviewReflection(today.pending_reflection!.id, "confirmed")}>Keep reflection</button><button className="secondary" onClick={() => reviewReflection(today.pending_reflection!.id, "dismissed")}>Dismiss</button></article> : <p className="muted">No reflection waiting for review.</p>}</section>
    <section><h2>History</h2>{history?.decisions.length || history?.reflections.length ? <ul>{history.decisions.slice(0, 5).map(item => <li key={item.id}><small>{item.review_status}</small> {item.statement}</li>)}{history.reflections.slice(0, 5).map(item => <li key={item.id}><small>{item.review_status} reflection</small> {item.statement}</li>)}</ul> : <p className="muted">No reviewed history yet.</p>}</section>
    <section><h2>GitHub polling</h2><p className="muted">{github?.token_saved ? "Token saved" : "No token"} · {github?.state ?? "disconnected"}{github?.detail ? ` · ${github.detail}` : ""}</p><form onSubmit={saveGitHub}><input type="password" aria-label="GitHub token" value={token} onChange={event => setToken(event.target.value)} placeholder="GitHub fine-grained token"/><button>Save update</button><button type="button" className="secondary" onClick={deleteGitHub}>Delete saved token</button><button type="button" onClick={pollGitHub} disabled={!github?.token_saved}>Poll GitHub</button></form><p className="muted">Needs a read-only fine-grained token with Pull requests access. Forge never displays it.</p></section>
    <footer>Forge never reads raw AI chat transcripts or edits <code>AGENTS.md</code> itself.</footer>
  </main>;
}
createRoot(document.getElementById("root")!).render(<App />);
