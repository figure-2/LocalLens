import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API_BASE =
  new URLSearchParams(window.location.search).get('api') ||
  import.meta.env.VITE_API_BASE_URL ||
  'http://127.0.0.1:8016';

const DEMO_WORKSPACE_ID = 'real-demo-v2';
const DEMO_DATA_DIR = '.locallens/real-demo-local-vlm-v2';
const DEMO_FOLDER = 'benchmarks/fixtures/locallens_real_demo';
const LOCAL_VLM_MODEL = 'HuggingFaceTB/SmolVLM-256M-Instruct';

const USERS = [
  { id: 'employee_hr', label: '로컬 사용자', caption: '공개 문서 + 개인 파일 예시' },
  { id: 'employee_eng', label: '엔지니어', caption: 'Engineering workspace' },
  { id: 'employee_sales', label: '세일즈 담당자', caption: 'Sales workspace' },
];

const SEARCH_MODES = [
  { id: 'local', label: 'Local Search', caption: '문서 내용으로 파일 찾기' },
  { id: 'image', label: 'Image Search', caption: '이미지 설명으로 이미지 찾기' },
  { id: 'pdf', label: 'PDF Visual Search', caption: 'PDF 텍스트와 표/이미지 caption 검색' },
  { id: 'ax', label: 'AX Workspace Extension', caption: '권한/근거 패킷 확장 예시' },
];

const SAMPLE_QUERIES = [
  { mode: 'local', text: 'selective indexing content hash skipped files' },
  { mode: 'local', text: 'evidence packet answer ready context source references' },
  { mode: 'image', text: 'blue security badge shield' },
  { mode: 'image', text: 'green architecture diagram flow' },
  { mode: 'pdf', text: 'leave approval table manager approval HR confirmation' },
  { mode: 'ax', text: '휴가 신청 절차' },
];

function formatScore(value) {
  if (typeof value !== 'number') return '0.00';
  return value.toFixed(2);
}

function modalityLabel(value) {
  const labels = {
    text: '텍스트',
    pdf_text: 'PDF',
    image: '이미지',
    slide_text: '슬라이드',
  };
  return labels[value] || value || '기타';
}

function buildSearchParams({ query, userId, mode, pdfSearchKind }) {
  const params = new URLSearchParams({ q: query, user_id: userId, top_k: '5' });
  if (mode === 'local') {
    params.set('modality', 'text');
    params.set('unit_type', 'document');
  }
  if (mode === 'image') params.set('modality', 'image');
  if (mode === 'pdf') {
    params.set('modality', 'text');
    params.set('ext', '.pdf');
    params.set('unit_type', pdfSearchKind === 'text' ? 'page' : 'pdf_visual_caption');
  }
  if (mode !== 'ax') {
    params.set('workspace_id', DEMO_WORKSPACE_ID);
    params.set('data_dir', DEMO_DATA_DIR);
  }
  return params;
}

function buildAgentFilters(mode) {
  if (mode === 'image') return { modality: 'image' };
  if (mode === 'pdf') return { document_type: 'pdf' };
  return {};
}

function buildLocalAgentResult({ query, userId, mode, results }) {
  const evidencePackets = results || [];
  const sourceRefs = evidencePackets.map((packet) => packet.source_ref);
  const snippets = evidencePackets.map((packet) => ({
    title: packet.title,
    source_ref: packet.source_ref,
    snippet: packet.snippet,
    match_type: packet.match_type,
    modality: packet.modality,
  }));
  const primary = evidencePackets[0];
  return {
    tool_name: 'locallens.local_search',
    tool_input: {
      query,
      user_id: userId,
      mode,
      top_k: 5,
    },
    evidence_packets: evidencePackets,
    answer_ready_context: {
      query,
      user_id: userId,
      mode,
      source_refs: sourceRefs,
      snippets,
      instruction:
        'Use only these LocalLens evidence packets. If the evidence is insufficient, say that the local file evidence is insufficient.',
    },
    mock_answer: primary
      ? `'${query}'에 대한 1차 근거는 '${primary.title}'의 ${primary.source_ref}입니다. 핵심 근거는 ${primary.snippet} 입니다.`
      : `'${query}'에 대해 사용할 수 있는 로컬 파일 근거를 찾지 못했습니다.`,
    claim_boundary:
      'This local Agent packet is created from LocalLens search results. It is an answer-preparation context, not a final LLM answer correctness proof.',
  };
}

function App() {
  const [userId, setUserId] = useState('employee_hr');
  const [mode, setMode] = useState('local');
  const [query, setQuery] = useState('');
  const [documents, setDocuments] = useState([]);
  const [results, setResults] = useState([]);
  const [agentResult, setAgentResult] = useState(null);
  const [status, setStatus] = useState('Demo folder를 동기화한 뒤 문서, 이미지, PDF 검색 시나리오를 실행하세요.');
  const [loading, setLoading] = useState(false);
  const [syncPath, setSyncPath] = useState(DEMO_FOLDER);
  const [syncReport, setSyncReport] = useState(null);
  const [syncLoading, setSyncLoading] = useState(false);
  const [pdfVlmMode, setPdfVlmMode] = useState('local-vlm');
  const [pdfVlmModelName, setPdfVlmModelName] = useState(LOCAL_VLM_MODEL);
  const [pdfSearchKind, setPdfSearchKind] = useState('visual');

  const selectedMode = useMemo(
    () => SEARCH_MODES.find((item) => item.id === mode) || SEARCH_MODES[0],
    [mode],
  );

  useEffect(() => {
    async function loadDocuments() {
      try {
        const response = await fetch(`${API_BASE}/api/v1/documents?user_id=${userId}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        setDocuments(payload.documents || []);
      } catch (error) {
        setStatus(`문서 목록을 불러오지 못했습니다: ${error.message}`);
      }
    }
    loadDocuments();
  }, [userId]);

  async function runSearch(event) {
    event?.preventDefault();
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      setStatus('검색어를 먼저 입력하세요.');
      return;
    }
    setLoading(true);
    setAgentResult(null);
    try {
      const params = buildSearchParams({ query: cleanQuery, userId, mode, pdfSearchKind });
      const endpoint = mode === 'ax' ? '/api/v1/search' : '/api/v1/local/search';
      const response = await fetch(`${API_BASE}${endpoint}?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setResults(payload.results || []);
      setStatus(`${selectedMode.label}: ${payload.results?.length || 0}개 결과`);
    } catch (error) {
      setStatus(`검색 실패: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function runAgentTool() {
    const cleanQuery = query.trim();
    if (!cleanQuery) {
      setStatus('Agent에 전달할 검색어를 먼저 입력하세요.');
      return;
    }
    setLoading(true);
    try {
      if (mode !== 'ax') {
        const params = buildSearchParams({ query: cleanQuery, userId, mode, pdfSearchKind });
        const response = await fetch(`${API_BASE}/api/v1/local/search?${params}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        const localResults = payload.results || [];
        setResults(localResults);
        setAgentResult(
          buildLocalAgentResult({
            query: cleanQuery,
            userId,
            mode,
            results: localResults,
          }),
        );
        setStatus(`Local Agent evidence packet: ${localResults.length}개`);
        return;
      }
      const response = await fetch(`${API_BASE}/api/v1/agent/tools/document-search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: cleanQuery,
          user_id: userId,
          top_k: 5,
          filters: buildAgentFilters(mode),
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setAgentResult(payload);
      setResults(payload.evidence_packets || []);
      setStatus(`Agent evidence packet: ${payload.evidence_packets?.length || 0}개`);
    } catch (error) {
      setStatus(`Agent tool 실패: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function runLocalSync(event) {
    event?.preventDefault();
    const cleanPath = syncPath.trim();
    if (!cleanPath) {
      setStatus('동기화할 로컬 폴더 경로를 입력하세요.');
      return;
    }
    setSyncLoading(true);
    setSyncReport(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/local/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root_path: cleanPath,
          workspace_id: DEMO_WORKSPACE_ID,
          data_dir: DEMO_DATA_DIR,
          pdf_visual_mode: 'off',
          pdf_ocr_mode: 'off',
          pdf_table_mode: 'off',
          pdf_vlm_mode: pdfVlmMode,
          pdf_vlm_model_name: pdfVlmModelName.trim(),
          max_progress_events: 40,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setSyncReport(payload);
      const report = payload.report || {};
      setStatus(
        `로컬 동기화 완료: added ${report.added || 0}, updated ${report.updated || 0}, deleted ${
          report.deleted || 0
        }, skipped ${report.skipped || 0}`,
      );
    } catch (error) {
      setStatus(`로컬 동기화 실패: ${error.message}`);
    } finally {
      setSyncLoading(false);
    }
  }

  function applySample(sample) {
    setMode(sample.mode);
    setQuery(sample.text);
    if (sample.mode === 'pdf') setPdfSearchKind('visual');
    setStatus('예시 검색어를 입력했습니다. 검색 버튼을 눌러 실행하세요.');
  }

  return (
    <main className="app-shell">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Local Multimodal Search</p>
          <h1>LocalLens</h1>
          <p className="hero-copy">
            로컬 텍스트, 이미지, PDF를 자연어로 찾는 멀티모달 검색기입니다. 업그레이드 버전에서는
            PostgreSQL 메타데이터와 Qdrant 벡터 검색을 연결하고, 검색 결과를 Agent가 사용할 수 있는
            근거 패킷으로 정규화합니다.
          </p>
        </div>
        <div className="hero-card">
          <strong>현재 시연 범위</strong>
          <span>local demo corpus 기준</span>
          <span>문서 검색 · 이미지 검색 · PDF visual caption</span>
        </div>
      </section>

      <section className="control-grid">
        <aside className="side-card">
          <h2>사용자 범위</h2>
          <div className="option-list">
            {USERS.map((user) => (
              <button
                key={user.id}
                className={userId === user.id ? 'option active' : 'option'}
                onClick={() => setUserId(user.id)}
                type="button"
              >
                <strong>{user.label}</strong>
                <span>{user.caption}</span>
              </button>
            ))}
          </div>

          <h2>검색 예시</h2>
          <div className="sample-list">
            {SAMPLE_QUERIES.map((sample) => (
              <button key={sample.text} type="button" onClick={() => applySample(sample)}>
                {sample.text}
              </button>
            ))}
          </div>
          <div className="scenario-note">
            <strong>시연 순서</strong>
            <span>1. Scan / Index</span>
            <span>2. 문서 내용 검색</span>
            <span>3. 이미지 설명 검색</span>
            <span>4. PDF 표/이미지 설명 검색</span>
          </div>
        </aside>

        <section className="search-card">
          <section className="sync-panel">
            <div>
              <p className="eyebrow small">File Sync</p>
              <h2>로컬 폴더 동기화</h2>
              <p>
                실제 demo folder의 문서 3개, 이미지 3개, PDF 2개를 인덱싱합니다. 동일 폴더를 다시
                실행하면 변경 없는 파일은 skipped로 분류됩니다.
              </p>
            </div>
            <div className="sync-options">
              <label>
                PDF VLM mode
                <select value={pdfVlmMode} onChange={(event) => setPdfVlmMode(event.target.value)}>
                  <option value="off">off</option>
                  <option value="mock-vlm">mock-vlm</option>
                  <option value="local-vlm">local-vlm</option>
                  <option value="clova-studio">clova-studio</option>
                </select>
              </label>
              <label>
                VLM model name
                <input
                  value={pdfVlmModelName}
                  onChange={(event) => setPdfVlmModelName(event.target.value)}
                  placeholder="예: HuggingFaceTB/SmolVLM-256M-Instruct"
                />
              </label>
            </div>
            <form className="sync-form" onSubmit={runLocalSync}>
              <input
                value={syncPath}
                onChange={(event) => setSyncPath(event.target.value)}
                placeholder="예: benchmarks/fixtures/corpus 또는 F:\\path\\to\\folder"
              />
              <button disabled={syncLoading} type="submit">
                {syncLoading ? '동기화 중' : 'Scan / Index'}
              </button>
            </form>
            {syncReport ? (
              <div className="sync-result">
                {[
                  'added',
                  'updated',
                  'deleted',
                  'skipped',
                  'failed',
                  'units',
                  'vlm_succeeded',
                ].map((key) => (
                  <div key={key}>
                    <strong>{syncReport.report?.[key] ?? 0}</strong>
                    <span>{key}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {syncReport?.progress_events?.length ? (
              <div className="progress-list">
                {syncReport.progress_events.slice(-5).map((event, index) => (
                  <span key={`${event.phase}-${event.relative_path}-${index}`}>
                    {event.phase} · {event.relative_path || 'root'} · {event.processed}/{event.total}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          <div className="mode-tabs">
            {SEARCH_MODES.map((item) => (
              <button
                key={item.id}
                className={mode === item.id ? 'mode active' : 'mode'}
                onClick={() => setMode(item.id)}
                type="button"
              >
                <strong>{item.label}</strong>
                <span>{item.caption}</span>
              </button>
            ))}
          </div>

          <form className="search-form" onSubmit={runSearch}>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="찾고 싶은 문서나 이미지 내용을 자연어로 입력하세요"
            />
            {mode === 'pdf' ? (
              <select
                className="pdf-kind-select"
                value={pdfSearchKind}
                onChange={(event) => setPdfSearchKind(event.target.value)}
              >
                <option value="visual">PDF visual caption</option>
                <option value="text">PDF text page</option>
              </select>
            ) : null}
            <button disabled={loading} type="submit">
              검색
            </button>
            <button disabled={loading} onClick={runAgentTool} type="button" className="secondary">
              근거 패킷 생성
            </button>
          </form>
          <p className="status-line">{loading ? '검색 중...' : status}</p>

          <div className="content-columns">
            <section>
              <div className="section-title">
                <h2>검색 결과</h2>
                <span>PostgreSQL keyword + Qdrant semantic</span>
              </div>
              <div className="result-list">
                {results.length === 0 ? (
                  <div className="empty-state">아직 검색 결과가 없습니다.</div>
                ) : (
                  results.map((item) => (
                    <article className="result-card" key={`${item.document_id}-${item.chunk_id}`}>
                      <div className="result-head">
                        <strong>{item.title}</strong>
                        <span>{modalityLabel(item.modality)}</span>
                      </div>
                      <p>{item.snippet}</p>
                      <div className="meta-row">
                        <span>{item.source_ref}</span>
                        <span>score {formatScore(item.score)}</span>
                        <span>{item.match_type}</span>
                      </div>
                    </article>
                  ))
                )}
              </div>
            </section>

            <section className="agent-panel">
              <div className="section-title">
                <h2>Agent Evidence Packet</h2>
                <span>검색 결과를 답변 전 근거로 전달</span>
              </div>
              {!agentResult ? (
                <div className="empty-state">
                  현재 검색 모드의 결과를 Agent가 사용할 수 있는 answer-ready context로 변환합니다.
                </div>
              ) : (
                <div className="agent-box">
                  <h3>Tool Contract</h3>
                  <div className="tool-contract">
                    <span>tool: {agentResult.tool_name}</span>
                    <span>mode: {agentResult.tool_input?.mode || 'ax'}</span>
                    <span>top_k: {agentResult.tool_input?.top_k || 5}</span>
                  </div>
                  <h3>Answer-ready Context</h3>
                  <p>{agentResult.mock_answer}</p>
                  <h3>Evidence snippets</h3>
                  <ul>
                    {(agentResult.answer_ready_context?.snippets || []).slice(0, 3).map((item) => (
                      <li key={`${item.source_ref}-${item.snippet}`}>
                        <strong>{item.title}</strong> · {item.snippet.slice(0, 90)}
                      </li>
                    ))}
                  </ul>
                  <h3>Source refs</h3>
                  <ul>
                    {(agentResult.answer_ready_context?.source_refs || []).map((ref) => (
                      <li key={ref}>{ref}</li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          </div>
        </section>
      </section>

      <section className="document-strip">
        <div className="section-title">
          <h2>AX Workspace 확장 예시 문서</h2>
          <span>{documents.length}개 항목</span>
        </div>
        <div className="doc-grid">
          {documents.map((doc) => (
            <article key={doc.document_id} className="doc-card">
              <strong>{doc.title}</strong>
              <span>{doc.document_type}</span>
              <small>{doc.document_id}</small>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
