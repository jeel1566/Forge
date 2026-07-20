import React, { useEffect, useMemo, useState } from "react";
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
type View = "overview" | "learning" | "handoffs" | "coordination" | "github";

const api = import.meta.env.VITE_FORGE_API ?? "";
const alertGuidance: Record<LearningAlert["kind"], string> = {
  possible_duplicate: "Ask the developer whether these cards should merge or remain separate.",
  possible_conflict: "Ask the developer which conflicting action is correct.",
  review_due: "Raise this review in developer chat. The active rule stays in place.",
  projection_repair: "Repair the managed Forge block markers, then retry the rule action.",
};

function safeList<T>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function normalizeCard(card: LearningCard): LearningCard { return { ...card, scope: safeList<string>(card.scope), alerts: safeList<LearningCard["alerts"][number]>(card.alerts), observations: safeList<CardObservation>(card.observations), rule_versions: safeList<CardRule>(card.rule_versions), verification_inputs: safeList<VerificationInput>(card.verification_inputs) }; }
function normalizeHandoff(handoff: SessionHandoff): SessionHandoff { return { ...handoff, scope: safeList<string>(handoff.scope), citations: safeList<Citation>(handoff.citations) }; }
function normalizeProjectionStatus(status: ProjectionStatus | null): ProjectionStatus | null { return status ? { projections: safeList<Projection>(status.projections), repair_alerts: safeList<ProjectionStatus["repair_alerts"][number]>(status.repair_alerts) } : null; }
function shortDate(value?: string | null) { return value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "Not yet"; }
function timeLabel(value?: string | null) { return value ? new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Not recorded"; }
function stateClass(state?: string | null) { return `state state-${(state || "unknown").replaceAll("_", "-")}`; }

function Mark({ name }: { name: string }) { return <span aria-hidden="true" className="mark">{name}</span>; }
function Empty({ title, detail }: { title: string; detail: string }) { return <div className="empty"><div className="empty-orb">+</div><strong>{title}</strong><p>{detail}</p></div>; }
function SectionHeading({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) { return <div className="section-heading"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>{action}</div>; }

function App() {
  const [workspace, setWorkspace] = useState("default");
  const [view, setView] = useState<View>("overview");
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
  const [loaded, setLoaded] = useState(false);

  const get = async <T,>(path: string, fallback: T, allowNotFound = false) => {
    try {
      const response = await fetch(`${api}${path}`);
      if (allowNotFound && response.status === 404) return fallback;
      if (!response.ok) {
        setError(`Forge returned ${response.status}. Retry after the local dashboard is ready.`);
        return fallback;
      }
      return await response.json() as T;
    } catch {
      setError("Forge is unavailable. Start the local dashboard or retry when it is online.");
      return fallback;
    }
  };

  const loadWorkspace = async () => {
    setError("");
    await Promise.all([
      get<Repository | null>(`/v1/workspaces/${workspace}/repository`, null, true).then(setRepository),
      get<Coordination | null>(`/v1/workspaces/${workspace}/coordination`, null).then(setCoordination),
      get<{ policy: RulePolicy } | null>(`/v1/workspaces/${workspace}/learning`, null).then(result => setPolicy(result?.policy ?? null)),
      get<ReusableRule[]>(`/v1/workspaces/${workspace}/reusable-rules`, []).then(result => setReusableRules(safeList<ReusableRule>(result))),
      get<ReusableRule[]>("/v1/reusable-rules", []).then(result => setReusableRequests(safeList<ReusableRule>(result))),
      get<LearningCard[]>(`/v1/workspaces/${workspace}/learning-cards`, []).then(result => setCards(safeList<LearningCard>(result).map(normalizeCard))),
      get<LearningAlert[]>(`/v1/workspaces/${workspace}/learning-alerts`, []).then(result => setAlerts(safeList<LearningAlert>(result))),
      get<ProjectionStatus | null>(`/v1/workspaces/${workspace}/projection-status`, null).then(result => setProjectionStatus(normalizeProjectionStatus(result))),
      get<SessionHandoff[]>(`/v1/workspaces/${workspace}/handoffs`, []).then(result => setHandoffs(safeList<SessionHandoff>(result).map(normalizeHandoff))),
      get<Evidence[]>(`/v1/workspaces/${workspace}/evidence`, []).then(setEvidence),
      get<GitHubPollStatus | null>(`/v1/workspaces/${workspace}/github/status`, null, true).then(setGithubPolling)
    ]);
    setLoaded(true);
  };

  useEffect(() => {
    void get<GitHubCredentials>("/v1/connectors/github", { token_saved: false, state: "disconnected" }).then(setGithub);
    void get<RegisteredRepository[]>("/v1/repositories", []).then(result => setRepositories(safeList<RegisteredRepository>(result)));
  }, []);

  useEffect(() => { loadWorkspace(); setSelectedCardId(null); }, [workspace]);
  useEffect(() => { setBaseRef(repository?.coordination_base_ref ?? ""); }, [repository?.coordination_base_ref]);
  useEffect(() => { setGithubPollingEnabled(githubPolling?.enabled ?? false); setGithubPollingInterval(String(githubPolling?.interval_seconds ?? 900)); }, [githubPolling?.enabled, githubPolling?.interval_seconds]);

  const selectedCard = cards.find(card => card.id === selectedCardId) ?? null;
  const activeRules = cards.filter(card => ["active", "verified"].includes(card.state)).length;
  const rateLimitPercent = githubPolling?.rate_limit_limit ? Math.round(((githubPolling.rate_limit_remaining ?? 0) / githubPolling.rate_limit_limit) * 100) : 0;
  const health = githubPolling?.health ?? githubPolling?.connector_state ?? github?.state ?? "offline";
  const workspaceName = repository?.path.split(/[\\/]/).filter(Boolean).at(-1) || workspace;

  const stats = useMemo(() => [
    { label: "Learning cards", value: cards.length, note: `${activeRules} active`, tone: "violet" },
    { label: "Needs review", value: alerts.length, note: alerts.length ? "Developer attention" : "All clear", tone: alerts.length ? "orange" : "mint" },
    { label: "Cited evidence", value: evidence.length, note: "Local facts only", tone: "blue" },
    { label: "GitHub health", value: health, note: githubPolling?.partial ? "Partial sync" : github?.token_saved ? "Connected locally" : "No token saved", tone: health === "healthy" ? "mint" : "orange" },
  ], [cards.length, activeRules, alerts.length, evidence.length, health, githubPolling?.partial, github?.token_saved]);

  const addRepository = async (event: React.FormEvent) => { event.preventDefault(); if (!repositoryPath.trim()) return; const response = await fetch(`${api}/v1/repositories`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ path: repositoryPath }) }); if (!response.ok) { setError((await response.json()).detail || "Could not register repository."); return; } const result = await response.json(); setRepositoryPath(""); void get<RegisteredRepository[]>("/v1/repositories", []).then(result => setRepositories(safeList<RegisteredRepository>(result))); setWorkspace(result.workspace_id); };
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

  if (error) return <main className="offline"><div className="offline-card"><div className="flare">×</div><p className="eyebrow">CONNECTION INTERRUPTED</p><h1>Forge is offline.</h1><p>{error}</p><button onClick={() => { setError(""); loadWorkspace(); }}>Try again <Mark name="→" /></button></div></main>;
  if (!loaded) return <main className="boot"><div className="forge-loader"><i /><i /><i /></div><p>Opening your local memory…</p></main>;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><span /></div><span>forge</span><em>v1</em></div>
      <nav aria-label="Main navigation">
        {([ ["overview", "Overview", "◈"], ["learning", "Learning system", "✦"], ["handoffs", "Session handoffs", "↗"], ["coordination", "Coordination", "⌘"], ["github", "GitHub sync", "◌"] ] as [View, string, string][]).map(([id, label, icon]) => <button key={id} className={view === id ? "nav-item active" : "nav-item"} onClick={() => setView(id)}><span>{icon}</span>{label}{id === "learning" && alerts.length > 0 && <b>{alerts.length}</b>}</button>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="privacy-note"><span>◉</span><p><strong>Local by design</strong>Nothing leaves this machine without your action.</p></div>
        <button className="workspace-switch" onClick={() => document.getElementById("workspace-picker")?.focus()}><span className="workspace-avatar">{workspaceName.slice(0, 1).toUpperCase()}</span><span><strong>{workspaceName}</strong><small>{repository?.branch || "No branch"}</small></span><Mark name="⌄" /></button>
      </div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div className="crumb"><span className="pulse" /> Forge <Mark name="/" /> <strong>{workspaceName}</strong></div><div className="top-actions"><button className="icon-button" title="Refresh workspace" onClick={loadWorkspace}>↻</button><span className={health === "healthy" ? "connection online" : "connection"}><i />{health === "healthy" ? "System live" : health}</span></div></header>
      <div className="page-wrap">
        {view === "overview" && <>
          <section className="hero reveal"><div><p className="eyebrow">LOCAL-FIRST ENGINEERING MEMORY</p><h1>Build better.<br /><span>Remember why.</span></h1><p className="hero-copy">Forge turns real development evidence into durable shared context—without collecting your chat.</p></div><div className="orbital" aria-hidden="true"><div className="orbital-ring"><span>✦</span></div><div className="orbital-core">F</div><small>safe<br />by design</small></div></section>
          <section className="stats-grid">{stats.map((stat, index) => <article className={`stat-card ${stat.tone} reveal delay-${index}`} key={stat.label}><p>{stat.label}</p><strong>{stat.value}</strong><span>{stat.note}</span><i /></article>)}</section>
          <section className="split-grid overview-grid">
            {handoffs[0] ? (
              <article className="panel intention-panel reveal">
                <SectionHeading eyebrow="SESSION FEEDBACK" title="Help Forge stay useful" action={<span className="live-label"><i />Active</span>} />
                <p className="muted-copy" style={{ margin: "8px 0 16px" }}>This saves only your explicit review answers as cited local data—never your chat.</p>
                <form className="stacked-form" onSubmit={saveFeedback} style={{ gap: "10px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                    <select aria-label="Was context useful" value={feedbackUseful} onChange={event => setFeedbackUseful(event.target.value)}>
                      <option value="yes">Context was useful</option>
                      <option value="partly">Context was partly useful</option>
                      <option value="no">Context was not useful</option>
                    </select>
                    <select aria-label="Rule assessment" value={feedbackAssessment} onChange={event => setFeedbackAssessment(event.target.value)}>
                      <option value="approve">Proposed rule described the issue</option>
                      <option value="revise">Proposed rule needs revision</option>
                      <option value="coaching_only">Use coaching only</option>
                      <option value="reject">Reject the proposed rule</option>
                    </select>
                  </div>
                  <textarea
                    aria-label="Irrelevant or missing context"
                    value={feedbackNotes}
                    onChange={event => setFeedbackNotes(event.target.value)}
                    placeholder="What was irrelevant or missing?"
                    style={{
                      width: "100%",
                      minHeight: "80px",
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                      borderRadius: "9px",
                      color: "#eae7df",
                      background: "rgba(1, 2, 5, 0.28)",
                      padding: "10px 11px",
                      fontFamily: "inherit",
                      resize: "vertical"
                    }}
                  />
                  <button style={{ alignSelf: "flex-start", padding: "10px 16px" }}>Save feedback</button>
                </form>
              </article>
            ) : (
              <article className="panel intention-panel reveal">
                <SectionHeading eyebrow="SESSION FEEDBACK" title="Feedback ready" />
                <Empty title="No active session" detail="Once you complete a session, you can assess its proposed rules and context here." />
              </article>
            )}
            <article className="panel signal-panel reveal delay-1"><SectionHeading eyebrow="SIGNAL" title="Developer attention" action={<button className="text-button" onClick={() => setView("learning")}>View all <Mark name="→" /></button>} />{alerts.length ? <div className="alert-stack">{alerts.slice(0, 2).map(alert => <div className="signal-row" key={alert.id}><span className="signal-icon">!</span><div><strong>{alert.kind.replaceAll("_", " ")}</strong><p>{alert.detail || alertGuidance[alert.kind]}</p></div></div>)}</div> : <Empty title="Everything is calm" detail="No developer decisions or recovery actions are waiting." />}</article>
          </section>
          <section className="split-grid overview-grid lower-grid">
            <article className="panel activity-panel reveal delay-2"><SectionHeading eyebrow="LATEST MEMORY" title="Session handoffs" action={<button className="text-button" onClick={() => setView("handoffs")}>Archive <Mark name="→" /></button>} />{handoffs.length ? <div className="handoff-preview">{handoffs.slice(0, 3).map((handoff, index) => <button key={handoff.id} className="handoff-row" onClick={() => setView("handoffs")}><span className="timeline-dot" /><div><p>{handoff.goal}</p><small>{handoff.agent} · {shortDate(handoff.created_at)} · {handoff.branch}</small></div><em>0{index + 1}</em></button>)}</div> : <Empty title="No handoff yet" detail="Finish an agent session to preserve its clean, cited handover." />}</article>
            <article className="panel health-panel reveal delay-3"><SectionHeading eyebrow="CONNECTOR" title="GitHub sync" action={<button className="text-button" onClick={() => setView("github")}>Manage <Mark name="→" /></button>} /><div className="health-layout"><div className="meter" style={{ "--meter": `${rateLimitPercent}%` } as React.CSSProperties}><div><strong>{githubPolling?.rate_limit_remaining ?? "—"}</strong><span>requests</span></div></div><div><span className={github?.token_saved ? "state state-healthy" : "state state-offline"}>{github?.token_saved ? "ready" : "not connected"}</span><p>{githubPolling?.last_success_at ? `Last sync ${timeLabel(githubPolling.last_success_at)}` : "Connect GitHub when you want local PR and review evidence."}</p></div></div></article>
          </section>
        </>}

        {view === "learning" && <section className="workspace-page">
          <div className="page-title">
            <div>
              <p className="eyebrow">THE LEARNING ENGINE</p>
              <h1>Evidence, not guesses.</h1>
              <p>Cards become rules only when independent, trusted evidence supports them.</p>
            </div>
            <div className="policy-switch">
              <span>Rule mode</span>
              <div>
                <button className={policy?.mode === "approval" ? "selected" : ""} onClick={() => savePolicy("approval")}>Approval</button>
                <button className={policy?.mode === "autonomous" ? "selected" : ""} onClick={() => savePolicy("autonomous")}>Autonomous</button>
              </div>
            </div>
          </div>
          <div className="learning-layout">
            <article className="panel card-list">
              <SectionHeading eyebrow={`${cards.length} CARDS`} title="Learning library" />
              {cards.length ? cards.map(card => <button className={selectedCardId === card.id ? "learning-row selected" : "learning-row"} key={card.id} onClick={() => setSelectedCardId(card.id)}><span className={stateClass(card.state)}>{card.state}</span><strong>{card.area || "Learning"}</strong><p>{card.trigger || "No trigger"} <Mark name="→" /> {card.action || "No action"}</p><small>{card.observations.length} evidence point{card.observations.length === 1 ? "" : "s"} · {card.scope.join(", ")}</small></button>) : <Empty title="No Learning Cards yet" detail="A configured validation-backed handoff creates the first card." />}
            </article>
            <article className="panel card-detail">
              {selectedCard ? <>
                <div className="card-detail-top"><span className={stateClass(selectedCard.state)}>{selectedCard.state}</span><span>{selectedCard.scope.join(" · ")}</span></div>
                <h2>{selectedCard.area || "Learning"}</h2>
                <p className="rule-statement">When <strong>{selectedCard.trigger || "a trigger occurs"}</strong>, {selectedCard.action || "no action is set yet"}.</p>
                <div className="detail-metrics"><span><strong>{selectedCard.observations.length}</strong> observations</span><span><strong>{selectedCard.verification_inputs.length}</strong> verifications</span><span><strong>{selectedCard.rule_versions.length}</strong> rule versions</span></div>
                <div className="timeline">
                  {selectedCard.observations.map(item => <div className="timeline-item" key={`${item.outcome_id}:${item.span_id}`}><i /><div><small>OBSERVATION · {shortDate(item.created_at)}</small><strong>{item.goal}</strong><p>{item.agent} · {item.validation}</p><blockquote>{item.citation_quote}</blockquote></div></div>)}
                  {selectedCard.rule_versions.map(rule => <div className="timeline-item rule-event" key={rule.id}><i /><div><small>RULE VERSION · {shortDate(rule.created_at)}</small><strong>{rule.statement}</strong><p>{rule.state}{rule.activated_at ? ` · active ${shortDate(rule.activated_at)}` : ""}</p></div></div>)}
                  {selectedCard.verification_inputs.map(input => <div className="timeline-item" key={input.id}><i /><div><small>LATER VERIFICATION · {shortDate(input.created_at)}</small><strong>{input.result.replaceAll("_", " ")}</strong><p>{input.summary}</p></div></div>)}
                </div>
              </> : <Empty title="Select a card" detail="Choose a Learning Card to explore its evidence-to-rule timeline." />}
            </article>
          </div>

          <div className="coordination-layout" style={{ marginTop: "12px" }}>
            <article className="panel">
              <SectionHeading eyebrow="CROSS-PROJECT PROMOTION" title="Reusable Rules" />
              <p className="muted-copy" style={{ margin: "6px 0 16px" }}>
                Reusable rules live only on this machine. Two independently evidence-gated projects can request promotion; nothing reaches another project until you approve it.
              </p>
              {reusableRequests.length ? (
                <div style={{ display: "grid", gap: "12px", marginBottom: "20px" }}>
                  <h3>Review inbox</h3>
                  {reusableRequests.map(rule => (
                    <div key={rule.id} className="signal-row" style={{ borderColor: "rgba(156,114,255,.25)", background: "rgba(156,114,255,.05)", display: "block" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <small className="state state-ready" style={{ fontSize: "0.55rem" }}>
                          Pending reusable rule · {rule.source_count ?? rule.sources?.length ?? 0}/2 projects
                        </small>
                        <button
                          className="outline-button"
                          disabled={!rule.ready_for_approval}
                          onClick={() => approveReusable(rule.id)}
                          style={{ padding: "4px 8px", fontSize: "0.6rem" }}
                        >
                          {rule.ready_for_approval ? "Approve reusable rule" : "Waiting for second project"}
                        </button>
                      </div>
                      <strong style={{ display: "block", marginTop: "8px", color: "#eeebe4", fontSize: "0.78rem" }}>{rule.statement}</strong>
                      <p className="muted-copy" style={{ fontSize: "0.65rem", marginTop: "4px" }}>
                        {rule.sources?.map(source => source.repository_path).join(" · ") || "Waiting for local project evidence."}
                      </p>
                    </div>
                  ))}
                </div>
              ) : null}

              <h3>Effective in this project</h3>
              {reusableRules.length ? (
                <div style={{ display: "grid", gap: "10px" }}>
                  {reusableRules.map(rule => (
                    <div key={rule.id} style={{ padding: "12px", border: "1px solid rgba(255,255,255,.07)", borderRadius: "10px", background: "rgba(255,255,255,.02)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <small className="state state-healthy" style={{ fontSize: "0.55rem" }}>
                          {rule.origin === "project_override" ? "Project override" : "Approved reusable rule"}
                        </small>
                        <div style={{ display: "flex", gap: "6px" }}>
                          <button
                            className="text-button"
                            onClick={() => { setOverrideRuleId(rule.id); setOverrideStatement(rule.statement); }}
                            style={{ fontSize: "0.65rem" }}
                          >
                            Replace locally
                          </button>
                          <button
                            className="text-button"
                            onClick={() => ignoreReusable(rule.id)}
                            style={{ fontSize: "0.65rem", color: "#f17d4a" }}
                          >
                            Ignore locally
                          </button>
                        </div>
                      </div>
                      <p style={{ margin: "8px 0 0", color: "#eeebe4", fontSize: "0.75rem" }}><strong>{rule.statement}</strong></p>
                      <small style={{ color: "#777e8e", fontSize: "0.58rem" }}>Scope: {rule.scope.join(", ")}</small>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="No approved reusable rules apply here" detail="Register and support rules in two local projects to request cross-project promotion." />
              )}

              {overrideRuleId && (
                <form onSubmit={saveOverride} className="stacked-form" style={{ marginTop: "15px" }}>
                  <label style={{ fontSize: "0.7rem", color: "#858b97" }}>Project rule override</label>
                  <div style={{ display: "flex", gap: "8px" }}>
                    <input aria-label="Project rule override" value={overrideStatement} onChange={event => setOverrideStatement(event.target.value)} style={{ flex: 1 }} />
                    <button>Save local replacement</button>
                    <button type="button" className="ghost-danger" onClick={() => setOverrideRuleId(null)}>Cancel</button>
                  </div>
                </form>
              )}
            </article>

            <article className="panel">
              <SectionHeading eyebrow="RULE PROJECTION" title="Managed Projections" />
              <p className="muted-copy" style={{ margin: "6px 0 16px" }}>
                Forge writes only its managed <code>AGENTS.md</code> block. Manual text outside that block remains untouched.
              </p>
              {projectionStatus?.repair_alerts.length ? (
                <div style={{ display: "grid", gap: "10px", marginBottom: "15px" }}>
                  {projectionStatus.repair_alerts.map(alert => (
                    <div key={alert.id} className="signal-row">
                      <span className="signal-icon">!</span>
                      <div>
                        <strong>Recovery required · {shortDate(alert.created_at)}</strong>
                        <p>{alert.detail}</p>
                        <small style={{ color: "#a89c98", fontSize: "0.6rem" }}>Restore valid Forge markers or move manual text outside the managed block. Then retry the rule action.</small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}

              {projectionStatus?.projections.length ? (
                <div className="worktree-list" style={{ maxHeight: "250px", overflowY: "auto" }}>
                  {projectionStatus.projections.map(item => (
                    <div key={item.id} style={{ padding: "10px 0", borderTop: "1px solid rgba(255,255,255,.07)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <strong style={{ fontSize: "0.75rem", color: "#e4e1da" }}>{item.operation}</strong>
                        <p style={{ margin: "2px 0 0" }}><code style={{ fontSize: "0.6rem", color: "#747b88" }}>{item.target_path}</code></p>
                        {item.detail && <small style={{ color: "#7d8390", fontSize: "0.55rem" }}>{item.detail}</small>}
                      </div>
                      <span className={stateClass(item.status)} style={{ fontSize: "0.55rem" }}>{item.status}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="No managed rule projections yet" detail="When rules are activated, their file-write outcomes are tracked here." />
              )}
            </article>
          </div>
        </section>}

        {view === "handoffs" && <section className="workspace-page"><div className="page-title"><div><p className="eyebrow">TRANSCRIPT-FREE CONTINUITY</p><h1>The work stays legible.</h1><p>Clean handovers, written by agents and grounded in persisted citations.</p></div><span className="big-count">{handoffs.length}<small>handoffs</small></span></div><div className="handoff-grid">{handoffs.length ? handoffs.map(handoff => <article className="panel handoff-card" key={handoff.id}><div className="handoff-meta"><span className="agent-pill">{handoff.agent}</span><small>{timeLabel(handoff.created_at)}</small></div><h2>{handoff.goal}</h2><div className="handoff-flow"><p><span>Problem</span>{handoff.problem}</p><p><span>What changed</span>{handoff.chosen_fix}</p><p><span>Why it works</span>{handoff.rationale}</p></div><footer><span>{handoff.category}</span><span>{handoff.scope.join(" · ")}</span><span>{handoff.citations.length} citations</span></footer></article>) : <Empty title="No handoffs recorded" detail="A future /forge_end records the compact, cited result of a session." />}</div></section>}

        {view === "coordination" && <section className="workspace-page"><div className="page-title"><div><p className="eyebrow">WORKING TOGETHER</p><h1>Clear lanes. No collisions.</h1><p>Forge reads Git facts only. It never merges work or resolves conflicts for you.</p></div><button className="outline-button" onClick={refreshEvidence}>↻ Refresh Git evidence</button></div><div className="coordination-layout"><article className="panel repo-panel"><SectionHeading eyebrow="ACTIVE REPOSITORY" title={workspaceName} /><label htmlFor="workspace-picker">Registered project</label><select id="workspace-picker" value={workspace} onChange={event => setWorkspace(event.target.value)}>{repository && !repositories.some(item => item.workspace_id === workspace) && <option value={workspace}>{workspace} · {repository.path}</option>}{repositories.map(item => <option key={item.workspace_id} value={item.workspace_id}>{item.workspace_id} · {item.path}</option>)}</select>{repository ? <><code>{repository.path}</code><p>{repository.branch || "Unknown branch"} · {repository.remote_url || "No remote configured"}</p></> : <p>No repository registered yet.</p>}<form className="add-repo" onSubmit={addRepository}><input aria-label="Repository path" value={repositoryPath} onChange={event => setRepositoryPath(event.target.value)} placeholder="Add a local Git repository path"/><button>Add</button></form></article><article className="panel base-panel"><SectionHeading eyebrow="COORDINATION BASE" title="Branch reference" /><p>Use one base to spot parallel work that may overlap.</p><form className="inline-form" onSubmit={saveBaseRef}><input aria-label="Coordination base branch" value={baseRef} onChange={event => setBaseRef(event.target.value)} placeholder="main"/><button>Save</button></form></article></div><section className="panel worktrees-panel"><SectionHeading eyebrow="GIT WORKTREES" title="Work in progress" action={<span className={coordination?.status === "ready" ? "state state-healthy" : "state state-offline"}>{coordination?.status || "unavailable"}</span>} />{coordination?.status === "ready" ? <div className="worktree-list">{coordination.worktrees.map(worktree => <article className="worktree" key={worktree.worktree_path}><span className={worktree.conflict_status.status === "conflicts_present" ? "worktree-icon warning" : "worktree-icon"}>⌘</span><div><strong>{worktree.branch || "detached HEAD"}</strong><p><code>{worktree.worktree_path}</code></p></div><div className="worktree-status"><span>{worktree.active_session_id ? "Active session" : worktree.recent_session_id ? "Recent session" : "No Forge session"}</span><small>{worktree.conflict_status.status === "conflicts_present" ? `Conflict: ${worktree.conflict_status.files?.join(", ")}` : `HEAD ${worktree.head_commit?.slice(0, 8) || "unknown"}`}</small></div></article>)}</div> : <Empty title="Coordination is unavailable" detail={coordination?.reason || "Register a repository to inspect its worktrees."} />}</section><section className="panel evidence-panel"><SectionHeading eyebrow="LOCAL GIT FACTS" title="Recent evidence" />{evidence.length ? <div className="evidence-list">{evidence.slice(0, 10).map(item => <div key={item.id}><code>{item.external_id?.slice(0, 7) || "local"}</code><span>{item.title}</span></div>)}</div> : <Empty title="No Git evidence yet" detail="Refresh Git evidence to make local development facts available." />}</section></section>}

        {view === "github" && <section className="workspace-page"><div className="page-title"><div><p className="eyebrow">LOCAL GITHUB CONNECTOR</p><h1>Reviews, safely in sync.</h1><p>Token stays local. Scheduling is opt-in. Forge saves safe metadata, never raw API payloads.</p></div><div className={github?.token_saved ? "connector-chip connected" : "connector-chip"}><i />{github?.token_saved ? "Connected locally" : "Not connected"}</div></div><div className="github-layout"><article className="panel github-status"><SectionHeading eyebrow="SYNC HEALTH" title="Connection pulse" /><div className="sync-hero"><div className={health === "healthy" ? "sync-orb good" : "sync-orb"}><span>◌</span></div><div><span className={stateClass(health)}>{health}</span><h3>{githubPolling?.partial ? "Partial sync paused safely" : github?.token_saved ? "Ready when you are" : "Connect your local token"}</h3><p>{githubPolling?.last_error || github?.detail || "No raw token, authorization header, or GitHub payload is displayed here."}</p></div></div><dl className="sync-facts"><div><dt>Last success</dt><dd>{timeLabel(githubPolling?.last_success_at)}</dd></div><div><dt>Next eligible poll</dt><dd>{timeLabel(githubPolling?.next_poll_at)}</dd></div><div><dt>Failures</dt><dd>{githubPolling?.consecutive_failures ?? 0}</dd></div></dl></article><article className="panel rate-panel"><SectionHeading eyebrow="RATE LIMIT" title="API headroom" /><div className="rate-figure"><div className="meter large" style={{ "--meter": `${rateLimitPercent}%` } as React.CSSProperties}><div><strong>{githubPolling?.rate_limit_remaining ?? "—"}</strong><span>remaining</span></div></div><p>{githubPolling?.rate_limit_limit ? `${rateLimitPercent}% available` : "Waiting for API response metadata"}</p></div><p className="muted-copy">Reset {timeLabel(githubPolling?.rate_limit_reset_at)}{githubPolling?.retry_after_at ? ` · retry after ${timeLabel(githubPolling.retry_after_at)}` : ""}</p></article></div><div className="github-layout setup-layout"><article className="panel token-panel"><SectionHeading eyebrow="LOCAL CREDENTIAL" title="GitHub access" /><form className="stacked-form" onSubmit={saveGitHub}><input type="password" aria-label="GitHub token" value={token} onChange={event => setToken(event.target.value)} placeholder="Fine-grained GitHub token"/><div><button>Save local token</button>{github?.token_saved && <button type="button" className="ghost-danger" onClick={deleteGitHub}>Remove</button>}</div></form><p className="form-note">Stored locally only. Forge never echoes your token.</p></article><article className="panel schedule-panel"><SectionHeading eyebrow="AUTOMATION" title="Polling schedule" /><form className="schedule-form" onSubmit={saveGitHubPolling}><label className="switch-row"><input type="checkbox" checked={githubPollingEnabled} onChange={event => setGithubPollingEnabled(event.target.checked)}/><span className="switch" /><span><strong>Schedule local polling</strong><small>Disabled by default. No background cloud service.</small></span></label><div className="interval-row"><label>Every <input type="number" min="60" max="86400" aria-label="GitHub polling interval seconds" value={githubPollingInterval} onChange={event => setGithubPollingInterval(event.target.value)}/> seconds</label><button>Save schedule</button></div></form><button className="poll-button" onClick={pollGitHub} disabled={!github?.token_saved || githubPolling?.in_progress}>{githubPolling?.in_progress ? "Polling safely…" : "Poll now"}<Mark name="→" /></button></article></div></section>}
      </div>
      <footer className="app-footer"><span>Forge stores cited local metadata, not raw AI chat transcripts.</span><span>Developers decide on duplicates, conflicts, and rules.</span></footer>
    </main>
  </div>;
}

createRoot(document.getElementById("root")!).render(<App />);
