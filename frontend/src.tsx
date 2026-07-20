import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Citation = { span_id: string; evidence_id: string; kind: string; title: string; quote: string };
type Repository = { path: string; remote_url?: string; branch?: string; coordination_base_ref?: string | null };
type RegisteredRepository = Repository & { workspace_id: string };
type GitHubCredentials = { token_saved: boolean; state: string; detail?: string };
type GitHubPollStatus = { enabled: boolean; interval_seconds: number; next_poll_at?: string | null; consecutive_failures: number; last_success_at?: string | null; last_error?: string | null; connector_state: string; connector_detail?: string | null; health?: string; in_progress?: boolean; partial?: boolean; rate_limit_remaining?: number | null; rate_limit_limit?: number | null; rate_limit_reset_at?: string | null; retry_after_at?: string | null };
type Evidence = { id: string; title: string; external_id: string };
type Worktree = { worktree_path: string; branch: string; head_commit?: string; active_session_id?: string | null; recent_session_id?: string | null; is_detached: boolean; is_locked: boolean; is_prunable: boolean; merge_status: { status: string; base_ref?: string }; conflict_status: { status: string; files?: string[] } };
type Coordination = { status: string; reason?: string; base_ref?: string | null; worktrees: Worktree[]; overlaps: { worktree_paths: string[]; files: string[] }[] };
type RulePolicy = { mode: "approval" | "autonomous" | null; configured: boolean };
type ReusableRule = { id: string; statement: string; category: string; scope: string[]; state: "pending" | "active" | "retracted"; source_count?: number; minimum_sources?: number; ready_for_approval?: boolean; origin?: "reusable_rule" | "project_override"; sources?: { repository_path: string; evidence_count: number }[] };
type CardObservation = { outcome_id: string; span_id: string; created_at: string; agent: string; goal: string; validation: string; citation_quote: string };
type CardRule = { id: string; statement: string; state: string; created_at: string; activated_at?: string | null; retracted_at?: string | null };
type VerificationInput = { id: string; source_kind: string; result: string; summary: string; developer_confirmed: boolean; created_at: string; applied_at?: string | null; evidence_title: string; citation_quote: string };
type LearningCard = { id: string; state: string; area?: string | null; trigger?: string | null; action?: string | null; scope: string[]; review_due_at?: string | null; alerts: { id: string; kind: string; related_card_id?: string | null }[]; observations: CardObservation[]; rule_versions: CardRule[]; verification_inputs: VerificationInput[] };
type LearningAlert = { id: string; card_id?: string | null; related_card_id?: string | null; kind: "possible_duplicate" | "possible_conflict" | "review_due" | "projection_repair"; detail?: string; created_at: string };
type Projection = { id: string; rule_version_id?: string | null; operation: string; status: "prepared" | "applied" | "failed" | "reverted"; target_path: string; detail?: string | null; created_at: string; completed_at?: string | null };
type ProjectionStatus = { projections: Projection[]; repair_alerts: { id: string; detail: string; created_at: string }[] };
type SessionHandoff = { id: string; agent: string; branch: string; scope: string[]; category: string; goal: string; problem: string; prior_approach: string; why_prior_approach_failed: string; chosen_fix: string; rationale: string; validation: string; risk: string; unresolved: string; proposed_rule: string; created_at: string; citations: Citation[] };

const api = import.meta.env.VITE_FORGE_API ?? "";
const alertGuidance: Record<LearningAlert["kind"], string> = {
  possible_duplicate: "Ask the developer whether these cards should merge or remain separate. Forge will not decide automatically.",
  possible_conflict: "Ask the developer which conflicting action is correct. Forge will not resolve the conflict automatically.",
  review_due: "Raise this due review in the developer chat. The active rule remains in place until the developer decides otherwise.",
  projection_repair: "Keep manual text outside Forge’s managed AGENTS.md block, repair the markers or managed block, then ask the agent to retry the rule action.",
};

function safeList<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function normalizeCard(card: LearningCard): LearningCard {
  return {
    ...card,
    scope: safeList<string>(card.scope),
    alerts: safeList<LearningCard["alerts"][number]>(card.alerts),
    observations: safeList<CardObservation>(card.observations),
    rule_versions: safeList<CardRule>(card.rule_versions),
    verification_inputs: safeList<VerificationInput>(card.verification_inputs),
  };
}

function normalizeHandoff(handoff: SessionHandoff): SessionHandoff {
  return { ...handoff, scope: safeList<string>(handoff.scope), citations: safeList<Citation>(handoff.citations) };
}

function normalizeProjectionStatus(status: ProjectionStatus | null): ProjectionStatus | null {
  return status ? { projections: safeList<Projection>(status.projections), repair_alerts: safeList<ProjectionStatus["repair_alerts"][number]>(status.repair_alerts) } : null;
}

function App() {
  const [workspace, setWorkspace] = useState("default");
  const [repository, setRepository] = useState<Repository | null>(null);
  const [repositories, setRepositories] = useState<RegisteredRepository[]>([]);
  const [repositoryPath, setRepositoryPath] = useState("");
  const [coordination, setCoordination] = useState<Coordination | null>(null);
  const [baseRef, setBaseRef] = useState("");
  const [policy, setPolicy] = useState<RulePolicy | null>(null);
  const [reusableRules, setReusableRules] = useState<ReusableRule[]>([]);
  const [reusableRequests, setReusableRequests] = useState<ReusableRule[]>([]);
  const [overrideRuleId, setOverrideRuleId] = useState<string | null>(null);
  const [overrideStatement, setOverrideStatement] = useState("");
  const [cards, setCards] = useState<LearningCard[]>([]);
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<LearningAlert[]>([]);
  const [projectionStatus, setProjectionStatus] = useState<ProjectionStatus | null>(null);
  const [handoffs, setHandoffs] = useState<SessionHandoff[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [github, setGithub] = useState<GitHubCredentials | null>(null);
  const [githubPolling, setGithubPolling] = useState<GitHubPollStatus | null>(null);
  const [githubPollingEnabled, setGithubPollingEnabled] = useState(false);
  const [githubPollingInterval, setGithubPollingInterval] = useState("900");
  const [token, setToken] = useState("");
  const [feedbackUseful, setFeedbackUseful] = useState("yes");
  const [feedbackNotes, setFeedbackNotes] = useState("");
  const [feedbackAssessment, setFeedbackAssessment] = useState("approve");
  const [error, setError] = useState("");

  const get = async <T,>(path: string, fallback: T) => {
    try {
      const response = await fetch(`${api}${path}`);
      return response.ok ? await response.json() as T : fallback;
    } catch {
      setError("Forge is unavailable. Start the local dashboard or retry when it is online.");
      return fallback;
    }
  };
  const loadWorkspace = () => {
    void get<Repository | null>(`/v1/workspaces/${workspace}/repository`, null).then(setRepository);
    void get<Coordination | null>(`/v1/workspaces/${workspace}/coordination`, null).then(setCoordination);
    void get<{ policy: RulePolicy } | null>(`/v1/workspaces/${workspace}/learning`, null).then(result => setPolicy(result?.policy ?? null));
    void get<ReusableRule[]>(`/v1/workspaces/${workspace}/reusable-rules`, []).then(result => setReusableRules(safeList<ReusableRule>(result)));
    void get<ReusableRule[]>("/v1/reusable-rules", []).then(result => setReusableRequests(safeList<ReusableRule>(result)));
    void get<LearningCard[]>(`/v1/workspaces/${workspace}/learning-cards`, []).then(result => setCards(safeList<LearningCard>(result).map(normalizeCard)));
    void get<LearningAlert[]>(`/v1/workspaces/${workspace}/learning-alerts`, []).then(result => setAlerts(safeList<LearningAlert>(result)));
    void get<ProjectionStatus | null>(`/v1/workspaces/${workspace}/projection-status`, null).then(result => setProjectionStatus(normalizeProjectionStatus(result)));
    void get<SessionHandoff[]>(`/v1/workspaces/${workspace}/handoffs`, []).then(result => setHandoffs(safeList<SessionHandoff>(result).map(normalizeHandoff)));
    void get<Evidence[]>(`/v1/workspaces/${workspace}/evidence`, []).then(setEvidence);
    void get<GitHubPollStatus | null>(`/v1/workspaces/${workspace}/github/status`, null).then(setGithubPolling);
  };
  useEffect(() => { void get<GitHubCredentials>("/v1/connectors/github", { token_saved: false, state: "disconnected" }).then(setGithub); void get<RegisteredRepository[]>("/v1/repositories", []).then(result => setRepositories(safeList<RegisteredRepository>(result))); }, []);
  useEffect(() => { loadWorkspace(); setSelectedCardId(null); }, [workspace]);
  useEffect(() => { setBaseRef(repository?.coordination_base_ref ?? ""); }, [repository?.coordination_base_ref]);
  useEffect(() => { setGithubPollingEnabled(githubPolling?.enabled ?? false); setGithubPollingInterval(String(githubPolling?.interval_seconds ?? 900)); }, [githubPolling?.enabled, githubPolling?.interval_seconds]);

  const selectedCard = cards.find(card => card.id === selectedCardId) ?? null;
  const addRepository = async (event: React.FormEvent) => { event.preventDefault(); if (!repositoryPath.trim()) return; const response = await fetch(`${api}/v1/repositories`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ path: repositoryPath }) }); if (!response.ok) { setError((await response.json()).detail || "Could not register repository."); return; } const result = await response.json(); setRepositoryPath(""); void get<RegisteredRepository[]>("/v1/repositories", []).then(setRepositories); setWorkspace(result.workspace_id); };
  const saveBaseRef = async (event: React.FormEvent) => { event.preventDefault(); await fetch(`${api}/v1/workspaces/${workspace}/coordination`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ base_ref: baseRef || null }) }); loadWorkspace(); };
  const savePolicy = async (mode: "approval" | "autonomous") => { const response = await fetch(`${api}/v1/workspaces/${workspace}/rule-policy`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode }) }); if (!response.ok) setError((await response.json()).detail || "Could not save rule policy."); else loadWorkspace(); };
  const refreshEvidence = async () => { if (!repository) return; await fetch(`${api}/v1/workspaces/${workspace}/git/imports`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ path: repository.path }) }); loadWorkspace(); };
  const saveGitHub = async (event: React.FormEvent) => { event.preventDefault(); if (!token) return; await fetch(`${api}/v1/connectors/github`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ token }) }); setToken(""); void get<GitHubCredentials>("/v1/connectors/github", { token_saved: false, state: "disconnected" }).then(setGithub); };
  const deleteGitHub = async () => { await fetch(`${api}/v1/connectors/github`, { method: "DELETE" }); void get<GitHubCredentials>("/v1/connectors/github", { token_saved: false, state: "disconnected" }).then(setGithub); };
  const pollGitHub = async () => { const response = await fetch(`${api}/v1/workspaces/${workspace}/github/poll`, { method: "POST" }); if (!response.ok) setError((await response.json()).detail || "GitHub polling failed."); loadWorkspace(); };
  const saveGitHubPolling = async (event: React.FormEvent) => { event.preventDefault(); const response = await fetch(`${api}/v1/workspaces/${workspace}/github/status`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: githubPollingEnabled, interval_seconds: Number(githubPollingInterval) }) }); if (!response.ok) setError((await response.json()).detail || "Could not update GitHub polling."); loadWorkspace(); };
  const approveReusable = async (ruleId: string) => { const response = await fetch(`${api}/v1/reusable-rules/${ruleId}/approval`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ developer_approved: true }) }); if (!response.ok) setError((await response.json()).detail || "Could not approve reusable rule."); else loadWorkspace(); };
  const saveOverride = async (event: React.FormEvent) => { event.preventDefault(); if (!overrideRuleId || !overrideStatement.trim()) return; const response = await fetch(`${api}/v1/workspaces/${workspace}/reusable-rules/${overrideRuleId}/override`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "replace", statement: overrideStatement }) }); if (!response.ok) setError((await response.json()).detail || "Could not save project override."); else { setOverrideRuleId(null); setOverrideStatement(""); loadWorkspace(); } };
  const ignoreReusable = async (ruleId: string) => { const response = await fetch(`${api}/v1/workspaces/${workspace}/reusable-rules/${ruleId}/override`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "ignore" }) }); if (!response.ok) setError((await response.json()).detail || "Could not ignore reusable rule."); else loadWorkspace(); };
  const saveFeedback = async (event: React.FormEvent) => { event.preventDefault(); const handoff = handoffs[0]; if (!handoff || !feedbackNotes.trim()) return; const response = await fetch(`${api}/v1/workspaces/${workspace}/handoffs/${handoff.id}/feedback`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ context_useful: feedbackUseful, irrelevant_or_missing: feedbackNotes, rule_assessment: feedbackAssessment }) }); if (!response.ok) setError((await response.json()).detail || "Could not save session feedback."); else { setFeedbackNotes(""); loadWorkspace(); } };

  if (error) return <main><h1>Forge is offline</h1><p>{error}</p><button onClick={() => { setError(""); loadWorkspace(); }}>Retry</button></main>;
  return <main>
    <header><p className="eyebrow">LOCAL-FIRST ENGINEERING MEMORY</p><h1>Today</h1><p>Forge stores cited local facts. Agents propose; developers decide.</p></header>
    <section><h2>Repository</h2><label className="muted" htmlFor="repository-select">Active project</label><select id="repository-select" value={workspace} onChange={event => setWorkspace(event.target.value)}>{repository && !repositories.some(item => item.workspace_id === workspace) && <option value={workspace}>{workspace} · {repository.path}</option>}{repositories.map(item => <option key={item.workspace_id} value={item.workspace_id}>{item.workspace_id} · {item.path}</option>)}</select>{repository ? <><p><code>{repository.path}</code></p><p className="muted">{repository.branch} · {repository.remote_url || "no remote"}</p><button onClick={refreshEvidence}>Refresh Git evidence</button></> : <p className="muted">No repository registered yet.</p>}<form onSubmit={addRepository}><input aria-label="Repository path" value={repositoryPath} onChange={event => setRepositoryPath(event.target.value)} placeholder="Add a local Git repository path"/><button>Add repository</button></form></section>
    <section><h2>Worktree coordination</h2>{coordination?.status === "ready" ? <><p className="muted">Base: <code>{coordination.base_ref || "unavailable"}</code> · Git facts only; Forge never merges or resolves conflicts.</p><form onSubmit={saveBaseRef}><input aria-label="Coordination base branch" value={baseRef} onChange={event => setBaseRef(event.target.value)} placeholder="Base branch, e.g. main"/><button>Save base</button><button type="button" className="secondary" onClick={loadWorkspace}>Refresh</button></form>{coordination.worktrees.map(item => <article key={item.worktree_path}><small>{item.active_session_id ? "active session" : item.recent_session_id ? "recent session" : "no Forge session"} · {item.is_detached ? "detached HEAD" : item.branch}</small><p><code>{item.worktree_path}</code></p><p className="muted">HEAD {item.head_commit?.slice(0, 12) || "unavailable"} · {item.merge_status.status}</p>{item.conflict_status.status === "conflicts_present" ? <p>Git conflict present: {item.conflict_status.files?.join(", ")}</p> : <p className="muted">No unresolved Git conflicts.</p>}</article>)}</> : <p className="muted">{coordination?.reason || "Coordination data is unavailable. Register a local Git repository first."}</p>}</section>
    <section><h2>Learning Cards</h2><p className="muted">{policy?.configured ? `${policy.mode} mode` : "Choose rule mode once for this workspace."} · Only configured validations can advance a card; later Git, GitHub, and local failures verify it with developer confirmation.</p><button className={policy?.mode === "approval" ? "secondary" : ""} onClick={() => savePolicy("approval")}>Approval mode</button><button className={policy?.mode === "autonomous" ? "secondary" : ""} onClick={() => savePolicy("autonomous")}>Autonomous mode</button>{cards.length ? cards.map(card => <article key={card.id}><button className="link" onClick={() => setSelectedCardId(card.id)}><small>{card.state} · {card.scope.join(", ")}</small><p><strong>{card.area || "Learning"}</strong> · {card.trigger || "No trigger"} → {card.action || "No action"}</p><p className="muted">{card.observations.length} observations · {card.verification_inputs.length} later verification inputs{card.review_due_at ? ` · review due ${card.review_due_at}` : ""}{card.alerts.length ? ` · ${card.alerts.length} pending alert${card.alerts.length === 1 ? "" : "s"}` : ""}</p></button></article>) : <p className="muted">No Learning Cards yet. A cited configured validation-backed handoff creates one.</p>}{selectedCard && <article><h3>Card timeline</h3><p className="muted">{selectedCard.state} · {selectedCard.scope.join(", ")}</p>{selectedCard.observations.map(item => <div key={`${item.outcome_id}:${item.span_id}`}><p><strong>Observation:</strong> {item.agent} · {item.goal}</p><p className="muted">{item.validation}</p><blockquote>{item.citation_quote}</blockquote></div>)}{selectedCard.rule_versions.map(rule => <div key={rule.id}><p><strong>Rule version:</strong> {rule.state} · {rule.statement}</p><p className="muted">Created {rule.created_at}{rule.activated_at ? ` · activated ${rule.activated_at}` : ""}{rule.retracted_at ? ` · retracted ${rule.retracted_at}` : ""}</p></div>)}{selectedCard.verification_inputs.map(input => <div key={input.id}><p><strong>Later verification:</strong> {input.source_kind.replaceAll("_", " ")} · {input.result}</p><p>{input.summary}</p><p className="muted">{input.developer_confirmed ? "Developer confirmed" : "Waiting for developer confirmation"}{input.applied_at ? ` · applied ${input.applied_at}` : ""}</p><blockquote>{input.evidence_title}: {input.citation_quote}</blockquote></div>)}</article>}</section>
    <section><h2>Reusable Rules</h2><p className="muted">Reusable rules live only on this machine. Two independently evidence-gated projects can request promotion; nothing reaches another project until you approve it.</p>{reusableRequests.length ? <><h3>Review inbox</h3>{reusableRequests.map(rule => <article key={rule.id}><small>Pending reusable rule · {rule.source_count ?? rule.sources?.length ?? 0}/2 projects</small><p><strong>{rule.statement}</strong></p><p className="muted">{rule.sources?.map(source => source.repository_path).join(" · ") || "Waiting for local project evidence."}</p><button disabled={!rule.ready_for_approval} onClick={() => approveReusable(rule.id)}>{rule.ready_for_approval ? "Approve reusable rule" : "Waiting for second project"}</button></article>)}</> : <p className="muted">No reusable-rule promotions waiting for review.</p>}<h3>Effective in this project</h3>{reusableRules.length ? reusableRules.map(rule => <article key={rule.id}><small>{rule.origin === "project_override" ? "Project override" : "Approved reusable rule"} · {rule.scope.join(", ")}</small><p><strong>{rule.statement}</strong></p><button className="secondary" onClick={() => { setOverrideRuleId(rule.id); setOverrideStatement(rule.statement); }}>Replace locally</button><button className="secondary" onClick={() => ignoreReusable(rule.id)}>Ignore locally</button></article>) : <p className="muted">No approved reusable rules apply here.</p>}{overrideRuleId && <form onSubmit={saveOverride}><input aria-label="Project rule override" value={overrideStatement} onChange={event => setOverrideStatement(event.target.value)} /><button>Save local replacement</button><button type="button" className="secondary" onClick={() => setOverrideRuleId(null)}>Cancel</button></form>}</section>
    <section><h2>Needs attention</h2><p className="muted">Forge never merges cards, resolves conflicts, or repairs managed rules automatically.</p>{alerts.length ? alerts.map(alert => <article key={alert.id}><small>{alert.kind.replaceAll("_", " ")} · {alert.created_at}</small><p>{alert.detail || alertGuidance[alert.kind]}</p><p className="muted">{alertGuidance[alert.kind]}</p></article>) : <p className="muted">No pending developer reviews or recovery actions.</p>}</section>
    <section><h2>Managed rule projection</h2><p className="muted">Forge writes only its managed `AGENTS.md` block. Manual text outside that block remains untouched.</p>{projectionStatus?.repair_alerts.length ? projectionStatus.repair_alerts.map(alert => <article key={alert.id}><small>Recovery required · {alert.created_at}</small><p>{alert.detail}</p><p className="muted">Restore valid Forge markers or move manual text outside the managed block. Then ask the agent to retry the pending rule action.</p></article>) : null}{projectionStatus?.projections.length ? projectionStatus.projections.map(item => <article key={item.id}><small>{item.operation} · {item.status} · {item.created_at}</small><p><code>{item.target_path}</code></p>{item.detail && <p className="muted">{item.detail}</p>}</article>) : <p className="muted">No managed rule projections yet.</p>}</section>
    <section><h2>Session Handoffs</h2><p className="muted">Clean summaries written by the agent itself. Forge never receives raw chat transcripts.</p>{handoffs.length ? handoffs.map(handoff => <article key={handoff.id}><small>{handoff.agent} · {handoff.branch} · {handoff.category} · {handoff.scope.join(", ")}</small><h3>{handoff.goal}</h3><p><strong>Problem:</strong> {handoff.problem}</p><p><strong>Prior approach:</strong> {handoff.prior_approach}</p><p><strong>Why it failed:</strong> {handoff.why_prior_approach_failed}</p><p><strong>Fix:</strong> {handoff.chosen_fix}</p><p><strong>Validation:</strong> {handoff.validation}</p><p><strong>Risk:</strong> {handoff.risk}</p><p><strong>Unresolved:</strong> {handoff.unresolved}</p><blockquote>{handoff.citations.map(citation => `${citation.title}: ${citation.quote}`).join("\n")}</blockquote></article>) : <p className="muted">No Session Handoffs recorded yet.</p>}</section>
    {handoffs[0] && <section><h2>Session feedback</h2><p className="muted">Help Forge stay useful. This saves only your explicit review answers as cited local data—never your chat.</p><form onSubmit={saveFeedback}><select aria-label="Was context useful" value={feedbackUseful} onChange={event => setFeedbackUseful(event.target.value)}><option value="yes">Context was useful</option><option value="partly">Context was partly useful</option><option value="no">Context was not useful</option></select><select aria-label="Rule assessment" value={feedbackAssessment} onChange={event => setFeedbackAssessment(event.target.value)}><option value="approve">Proposed rule described the issue</option><option value="revise">Proposed rule needs revision</option><option value="coaching_only">Use coaching only</option><option value="reject">Reject the proposed rule</option></select><textarea aria-label="Irrelevant or missing context" value={feedbackNotes} onChange={event => setFeedbackNotes(event.target.value)} placeholder="What was irrelevant or missing?"/><button>Save feedback</button></form></section>}
    <section><h2>Recent Git evidence</h2>{evidence.length ? <ul>{evidence.map(item => <li key={item.id}><code>{item.external_id?.slice(0, 7) || "local"}</code> {item.title}</li>)}</ul> : <p className="muted">No Git evidence imported yet.</p>}</section>
    <section><h2>GitHub polling</h2><p className="muted">{github?.token_saved ? "Token saved" : "No token"} · {githubPolling?.health ?? githubPolling?.connector_state ?? github?.state ?? "disconnected"}{githubPolling?.last_error ? ` · recovery: ${githubPolling.last_error}` : github?.detail ? ` · ${github.detail}` : ""}</p><form onSubmit={saveGitHub}><input type="password" aria-label="GitHub token" value={token} onChange={event => setToken(event.target.value)} placeholder="GitHub fine-grained token"/><button>Save update</button><button type="button" className="secondary" onClick={deleteGitHub}>Delete saved token</button><button type="button" onClick={pollGitHub} disabled={!github?.token_saved || githubPolling?.in_progress}>Poll now</button></form><form onSubmit={saveGitHubPolling}><label className="muted"><input type="checkbox" checked={githubPollingEnabled} onChange={event => setGithubPollingEnabled(event.target.checked)}/> Schedule local polling</label><input type="number" min="60" max="86400" aria-label="GitHub polling interval seconds" value={githubPollingInterval} onChange={event => setGithubPollingInterval(event.target.value)}/><button>Save schedule</button></form><p className="muted">{githubPolling?.enabled ? `Every ${githubPolling.interval_seconds}s · next ${githubPolling.next_poll_at ?? "soon"} · failures ${githubPolling.consecutive_failures}` : "Scheduled polling is off."}{githubPolling?.last_success_at ? ` · last success ${githubPolling.last_success_at}` : ""}{githubPolling?.partial ? " · Partial sync: configured limit reached; Forge will resume next poll." : ""}</p><p className="muted">Rate limit {githubPolling?.rate_limit_remaining ?? "unknown"}/{githubPolling?.rate_limit_limit ?? "unknown"}{githubPolling?.rate_limit_reset_at ? ` · resets ${githubPolling.rate_limit_reset_at}` : ""}{githubPolling?.retry_after_at ? ` · retry after ${githubPolling.retry_after_at}` : ""}. Forge never displays the token; scheduling remains local and opt-in.</p></section>
    <footer>Forge stores cited local metadata, not raw AI chat transcripts. Developers remain responsible for duplicate, conflict, and rule-review decisions.</footer>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
