"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_DATAPILOT_API ?? "http://127.0.0.1:8000/api/v1";

type RunSummary = {
  run_id: string;
  status: "running" | "succeeded" | "failed" | "rejected";
  question: string;
  model_name: string;
  started_at: string;
  duration_ms: number | null;
};

type ChartSeries = { name: string; x: Array<string | number | boolean | null>; y: number[] };
type ChartSpec = {
  chart_id: string;
  chart_type: "bar" | "line" | "scatter" | "area" | "histogram" | "box" | "heatmap";
  title: string;
  description: string;
  x_label: string;
  y_label: string;
  series: ChartSeries[];
};

type RunRecord = RunSummary & {
  result: null | {
    question: string;
    duration_ms: number;
    model_name: string;
    sql_candidate: { sql: string };
    sql_validation: { normalized_sql: string; risk_level: string; referenced_tables: string[] };
    query_result: { row_count: number; query_hash: string; truncated: boolean };
    narrative: { summary: string; findings: string[]; limitations: string[] };
    generated_python_analysis: null | {
      classification: string;
      profile: string;
      generated_code: string;
      output: {
        summary_metrics: Record<string, string | number | boolean | null>;
        visualizations: ChartSpec[];
        report_markdown: string | null;
      };
    };
  };
  error: null | { code: string; message: string; retryable: boolean };
};

const chartColors = ["#1d4ed8", "#0f766e", "#d97706", "#7c3aed", "#be123c"];

function StatusBadge({ status }: { status: RunSummary["status"] }) {
  const labels = { running: "运行中", succeeded: "已完成", failed: "失败", rejected: "已拒绝" };
  return <span className={`status status-${status}`}><i />{labels[status]}</span>;
}

function ChartPanel({ spec }: { spec: ChartSpec }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const width = Math.max(canvas.parentElement?.clientWidth ?? 500, 320);
      const height = 280;
      const scale = window.devicePixelRatio || 1;
      canvas.width = width * scale; canvas.height = height * scale;
      canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d"); if (!ctx) return;
      ctx.scale(scale, scale); ctx.clearRect(0, 0, width, height);
      const pad = { left: 52, right: 18, top: 20, bottom: 48 };
      const plotW = width - pad.left - pad.right; const plotH = height - pad.top - pad.bottom;
      const values = spec.series.flatMap((series) => series.y);
      const min = spec.chart_type === "scatter" ? Math.min(0, ...values) : 0;
      const max = Math.max(...values, 1); const range = max - min || 1;
      ctx.strokeStyle = "#e6e9ef"; ctx.lineWidth = 1; ctx.fillStyle = "#667085"; ctx.font = "10px Segoe UI";
      for (let i = 0; i <= 4; i += 1) {
        const y = pad.top + (plotH * i) / 4; ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
        const label = max - (range * i) / 4; ctx.fillText(label.toLocaleString(undefined, { maximumFractionDigits: 1 }), 3, y + 3);
      }
      const count = Math.max(spec.series[0]?.x.length ?? 1, 1);
      const yPos = (value: number) => pad.top + plotH - ((value - min) / range) * plotH;
      if (["bar", "histogram", "box", "heatmap"].includes(spec.chart_type)) {
        const groupW = plotW / count; const barW = Math.max(2, (groupW * 0.72) / spec.series.length);
        spec.series.forEach((series, sIndex) => series.y.forEach((value, index) => {
          const x = pad.left + index * groupW + groupW * 0.14 + sIndex * barW; const y = yPos(value);
          ctx.fillStyle = chartColors[sIndex % chartColors.length]; ctx.fillRect(x, y, barW - 2, pad.top + plotH - y);
        }));
      } else {
        spec.series.forEach((series, sIndex) => {
          ctx.strokeStyle = chartColors[sIndex % chartColors.length]; ctx.fillStyle = chartColors[sIndex % chartColors.length]; ctx.lineWidth = 2; ctx.beginPath();
          series.y.forEach((value, index) => { const x = pad.left + (plotW * index) / Math.max(count - 1, 1); const y = yPos(value); if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); if (spec.chart_type === "scatter") { ctx.moveTo(x + 3, y); ctx.arc(x, y, 3, 0, Math.PI * 2); } });
          if (spec.chart_type === "area") { ctx.lineTo(width - pad.right, pad.top + plotH); ctx.lineTo(pad.left, pad.top + plotH); ctx.globalAlpha = .16; ctx.fill(); ctx.globalAlpha = 1; }
          ctx.stroke();
        });
      }
      const labels = spec.series[0]?.x ?? [];
      const labelStep = Math.max(1, Math.ceil(labels.length / 7));
      labels.forEach((label, index) => { if (index % labelStep !== 0) return; const x = pad.left + (plotW * index) / Math.max(count - 1, 1); ctx.save(); ctx.translate(x, height - 30); ctx.rotate(-0.35); ctx.fillStyle = "#667085"; ctx.fillText(String(label).slice(0, 14), 0, 0); ctx.restore(); });
      spec.series.forEach((series, index) => { ctx.fillStyle = chartColors[index % chartColors.length]; ctx.fillRect(pad.left + index * 115, 2, 9, 9); ctx.fillStyle = "#475467"; ctx.fillText(series.name.slice(0, 14), pad.left + 14 + index * 115, 10); });
    };
    draw(); const observer = new ResizeObserver(draw); if (canvas.parentElement) observer.observe(canvas.parentElement); return () => observer.disconnect();
  }, [spec]);
  return (
    <article className="chart-card">
      <header><div><h3>{spec.title}</h3><p>{spec.description}</p></div><span>{spec.chart_type}</span></header>
      <div className="chart"><canvas ref={canvasRef} role="img" aria-label={`${spec.title}：${spec.description}`} /></div>
    </article>
  );
}

export default function Home() {
  const [question, setQuestion] = useState("统计不同订单状态的订单数量，生成图表并形成分析报告");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<RunRecord | null>(null);
  const [tab, setTab] = useState<"overview" | "charts" | "sql" | "python" | "report">("overview");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const loadRun = useCallback(async (runId: string) => {
    const response = await fetch(`${API_BASE}/agent/runs/${runId}`);
    if (!response.ok) throw new Error("无法读取运行详情");
    setSelected(await response.json());
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/agent/runs?limit=30`);
      if (!response.ok) throw new Error();
      const page = await response.json();
      setRuns(page.items);
      if (!selected && page.items[0]) await loadRun(page.items[0].run_id);
      setMessage("");
    } catch {
      setMessage("后端尚未连接，请确认 DataPilot API 已在 8000 端口启动。");
    }
  }, [loadRun, selected]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadRuns(), 0);
    return () => window.clearTimeout(initialLoad);
  }, [loadRuns]);

  async function analyze() {
    if (question.trim().length < 3) return;
    setBusy(true); setMessage("正在同步分析：规划 SQL、执行查询、生成 Python、图表与报告…");
    try {
      const response = await fetch(`${API_BASE}/agent/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, allow_generated_python: true, include_visualizations: true, include_report: true }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "分析失败");
      await loadRuns(); await loadRun(body.run_id); setTab("overview"); setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "分析失败");
      await loadRuns();
    } finally { setBusy(false); }
  }

  const result = selected?.result;
  const generated = result?.generated_python_analysis;
  const charts = generated?.output.visualizations ?? [];
  const metrics = generated?.output.summary_metrics ?? {};

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">DP</div><div><strong>DataPilot</strong><span>Auditable Analytics</span></div></div>
        <nav><button className="active">▦ <span>分析工作台</span></button><button>⌕ <span>数据源</span></button><button>⌘ <span>安全策略</span></button></nav>
        <div className="history-head"><span>最近运行</span><button onClick={() => void loadRuns()} aria-label="刷新历史">↻</button></div>
        <div className="run-list">
          {runs.map((run) => <button key={run.run_id} className={selected?.run_id === run.run_id ? "selected" : ""} onClick={() => void loadRun(run.run_id)}><StatusBadge status={run.status} /><strong>{run.question}</strong><small>{new Date(run.started_at).toLocaleString("zh-CN")}</small></button>)}
        </div>
        <div className="security-note"><span>●</span><div><strong>安全边界已启用</strong><small>只读 SQL · 隔离 Python</small></div></div>
      </aside>

      <section className="workspace">
        <header className="topbar"><div><span className="eyebrow">DATA ANALYSIS AGENT</span><h1>分析工作台</h1></div><div className="top-actions"><span className="model-pill">DeepSeek V4 Flash</span><a href={`${API_BASE.replace("/api/v1", "")}/docs`} target="_blank" rel="noreferrer">API 文档 ↗</a></div></header>
        <section className="composer">
          <label htmlFor="question">向数据提问</label>
          <textarea id="question" value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void analyze(); }} />
          <div><div className="capabilities"><span>SQL</span><span>Python</span><span>图表</span><span>报告</span></div><button className="run-button" disabled={busy} onClick={() => void analyze()}>{busy ? "分析中…" : "开始分析 →"}</button></div>
          {message && <p className="message">{message}</p>}
        </section>

        {selected ? <section className="result-area">
          <div className="run-title"><div><StatusBadge status={selected.status} /><h2>{selected.question}</h2><p>Run ID {selected.run_id}</p></div>{result && <div className="run-meta"><span>{result.query_result.row_count.toLocaleString()} 行</span><span>{(result.duration_ms / 1000).toFixed(1)} 秒</span><span>{result.model_name}</span></div>}</div>
          <div className="tabs">{(["overview", "charts", "sql", "python", "report"] as const).map((name) => <button key={name} className={tab === name ? "active" : ""} onClick={() => setTab(name)}>{{overview:"概览",charts:`图表 ${charts.length}`,sql:"SQL",python:"Python",report:"报告"}[name]}</button>)}</div>

          {selected.error && <div className="error-card"><strong>{selected.error.code}</strong><p>{selected.error.message}</p></div>}
          {result && tab === "overview" && <div className="overview-grid"><article className="summary-card"><span>EXECUTIVE SUMMARY</span><h3>分析结论</h3><p>{result.narrative.summary}</p><ul>{result.narrative.findings.map((f) => <li key={f}>{f}</li>)}</ul></article><aside className="metrics-card"><span>KEY METRICS</span>{Object.keys(metrics).length ? Object.entries(metrics).slice(0, 6).map(([key, value]) => <div key={key}><small>{key.replaceAll("_", " ")}</small><strong>{typeof value === "number" ? value.toLocaleString(undefined, {maximumFractionDigits: 3}) : String(value)}</strong></div>) : <div><small>query rows</small><strong>{result.query_result.row_count}</strong></div>}<div><small>risk level</small><strong>{result.sql_validation.risk_level}</strong></div></aside></div>}
          {result && tab === "charts" && <div className="charts-grid">{charts.length ? charts.map((chart) => <ChartPanel key={chart.chart_id} spec={chart} />) : <div className="empty-state">本次运行没有生成图表。重新分析并保持“图表”能力启用。</div>}</div>}
          {result && tab === "sql" && <div className="code-panel"><header><span>已执行的只读 SQL</span><small>{result.sql_validation.referenced_tables.join(" · ")}</small></header><pre>{result.sql_validation.normalized_sql}</pre></div>}
          {result && tab === "python" && <div className="code-panel"><header><span>DeepSeek 生成的 Python</span><small>{generated ? `${generated.profile} · ${generated.classification}` : "使用已验证函数，无生成代码"}</small></header><pre>{generated?.generated_code ?? "# 本次分析由 DataPilot 已验证的确定性函数完成。"}</pre></div>}
          {result && tab === "report" && <div className="report-panel"><div className="report-actions"><div><span>ANALYSIS REPORT</span><h3>可审计分析报告</h3></div><a className="download" href={`${API_BASE}/agent/runs/${selected.run_id}/report`}>下载 Markdown ↓</a></div><div className="report-copy"><p>{generated?.output.report_markdown ?? result.narrative.summary}</p><h4>局限性</h4><ul>{result.narrative.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div></div>}
        </section> : <div className="empty-state">提交一个问题，开始第一项可审计分析。</div>}
      </section>
    </main>
  );
}
