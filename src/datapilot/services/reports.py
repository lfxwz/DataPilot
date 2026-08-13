"""Trusted report rendering from validated analysis results."""

from datapilot.domain.agent import AgentAnalysisResult


def render_markdown_report(result: AgentAnalysisResult) -> str:
    """Return generated Markdown or a deterministic evidence-based fallback."""

    generated = result.generated_python_analysis
    if generated is not None and generated.output.report_markdown:
        return generated.output.report_markdown.strip() + "\n"

    findings = "\n".join(f"- {finding}" for finding in result.narrative.findings)
    limitations = "\n".join(f"- {item}" for item in result.narrative.limitations)
    return (
        f"# DataPilot 分析报告\n\n"
        f"## 分析问题\n\n{result.question}\n\n"
        f"## 摘要\n\n{result.narrative.summary}\n\n"
        f"## 主要发现\n\n{findings}\n\n"
        f"## 局限性\n\n{limitations}\n\n"
        f"## 审计信息\n\n"
        f"- Run ID: `{result.run_id}`\n"
        f"- Model: `{result.model_name}`\n"
        f"- Query hash: `{result.query_result.query_hash}`\n"
        f"- Rows: `{result.query_result.row_count}`\n"
        f"- Duration: `{result.duration_ms:.2f} ms`\n"
    )
