"""Static admission policy for model-generated Python.

This policy is defense in depth. Accepted code must still execute inside the
resource-limited, network-disabled Docker sandbox.
"""

import ast
from hashlib import sha256

from datapilot.domain.generated_python import (
    PythonPolicyIssue,
    PythonPolicyValidation,
    SandboxProfile,
)

_BASE_IMPORTS = frozenset(
    {
        "collections",
        "datetime",
        "decimal",
        "functools",
        "itertools",
        "json",
        "math",
        "networkx",
        "numpy",
        "openpyxl",
        "pandas",
        "polars",
        "plotly",
        "matplotlib",
        "pyarrow",
        "seaborn",
        "scipy",
        "sklearn",
        "statistics",
        "statsmodels",
        "sympy",
        "torch",
        "xgboost",
        "lightgbm",
    }
)
_PROFILE_IMPORTS = {
    SandboxProfile.ANALYTICS: _BASE_IMPORTS,
    SandboxProfile.DEEP_LEARNING: _BASE_IMPORTS,
}
_DENIED_BARE_CALLS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "exit",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "open",
        "quit",
        "setattr",
        "vars",
    }
)
_DENIED_ATTRIBUTE_CALLS = frozenset(
    {
        "fetch_20newsgroups",
        "fetch_california_housing",
        "fetch_covtype",
        "fetch_kddcup99",
        "fetch_lfw_pairs",
        "fetch_lfw_people",
        "fetch_olivetti_faces",
        "fetch_openml",
        "download_and_extract_archive",
        "download_url",
        "fromfile",
        "genfromtxt",
        "load",
        "load_library",
        "loadmat",
        "load_model",
        "loadtxt",
        "memmap",
        "read_csv",
        "read_excel",
        "read_feather",
        "read_fwf",
        "read_hdf",
        "read_html",
        "read_json",
        "read_clipboard",
        "read_gbq",
        "read_orc",
        "read_parquet",
        "read_pickle",
        "read_sas",
        "read_spss",
        "read_sql",
        "read_stata",
        "read_table",
        "read_xml",
        "save",
        "savemat",
        "save_model",
        "savetxt",
        "to_csv",
        "to_clipboard",
        "to_excel",
        "to_feather",
        "to_hdf",
        "to_json",
        "to_orc",
        "to_parquet",
        "to_pickle",
        "to_sql",
        "tofile",
        "urlretrieve",
        "write_html",
        "write_image",
        "savefig",
    }
)
_ALLOWED_TOP_LEVEL = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.Assign,
    ast.AnnAssign,
)


class PythonSafetyPolicy:
    """Reject dangerous syntax before a generated program reaches Docker."""

    def __init__(self, *, max_ast_nodes: int = 5000) -> None:
        if max_ast_nodes < 1:
            raise ValueError("max_ast_nodes must be positive")
        self._max_ast_nodes = max_ast_nodes

    def validate(self, code: str, profile: SandboxProfile) -> PythonPolicyValidation:
        code_hash = sha256(code.encode("utf-8")).hexdigest()
        issues: list[PythonPolicyIssue] = []
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            issues.append(
                PythonPolicyIssue(
                    code="syntax_error",
                    message="Generated Python is not syntactically valid.",
                    line=exc.lineno,
                )
            )
            return PythonPolicyValidation(accepted=False, code_hash=code_hash, issues=issues)

        nodes = list(ast.walk(tree))
        if len(nodes) > self._max_ast_nodes:
            issues.append(
                PythonPolicyIssue(
                    code="program_too_complex",
                    message=f"AST node count exceeds {self._max_ast_nodes}.",
                )
            )

        allowed_imports = _PROFILE_IMPORTS[profile]
        for statement in tree.body:
            if not isinstance(statement, _ALLOWED_TOP_LEVEL):
                issues.append(
                    PythonPolicyIssue(
                        code="top_level_execution",
                        message=(
                            "Only imports, function definitions, and constants are allowed "
                            "at top level."
                        ),
                        line=getattr(statement, "lineno", None),
                    )
                )
            elif isinstance(statement, ast.Assign | ast.AnnAssign):
                value = statement.value
                try:
                    if value is None:
                        raise ValueError
                    ast.literal_eval(value)
                except (ValueError, TypeError):
                    issues.append(
                        PythonPolicyIssue(
                            code="non_constant_top_level_assignment",
                            message="Top-level assignments must contain literal constants only.",
                            line=statement.lineno,
                        )
                    )

        for node in nodes:
            if isinstance(node, ast.Import | ast.ImportFrom):
                modules = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for module in modules:
                    root = module.split(".", maxsplit=1)[0]
                    if root not in allowed_imports:
                        issues.append(
                            PythonPolicyIssue(
                                code="import_not_allowed",
                                message=(
                                    f"Import root {root!r} is not allowed for profile {profile}."
                                ),
                                line=node.lineno,
                            )
                        )
            elif isinstance(node, ast.Call):
                call_name = self._call_name(node.func)
                denied = (isinstance(node.func, ast.Name) and call_name in _DENIED_BARE_CALLS) or (
                    isinstance(node.func, ast.Attribute) and call_name in _DENIED_ATTRIBUTE_CALLS
                )
                if denied:
                    issues.append(
                        PythonPolicyIssue(
                            code="call_not_allowed",
                            message=f"Call to {call_name!r} is not allowed.",
                            line=node.lineno,
                        )
                    )
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                issues.append(
                    PythonPolicyIssue(
                        code="dunder_access",
                        message="Dunder attribute access is not allowed.",
                        line=node.lineno,
                    )
                )
            elif isinstance(node, ast.Name) and node.id.startswith("__"):
                issues.append(
                    PythonPolicyIssue(
                        code="dunder_name",
                        message="Dunder names are not allowed.",
                        line=node.lineno,
                    )
                )

        analyze_functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "analyze"
        ]
        if len(analyze_functions) != 1:
            issues.append(
                PythonPolicyIssue(
                    code="invalid_entrypoint",
                    message="Exactly one top-level analyze(data) function is required.",
                )
            )
        elif len(analyze_functions[0].args.args) != 1:
            issues.append(
                PythonPolicyIssue(
                    code="invalid_entrypoint_signature",
                    message="The analyze entrypoint must accept exactly one positional argument.",
                    line=analyze_functions[0].lineno,
                )
            )

        return PythonPolicyValidation(
            accepted=not issues,
            code_hash=code_hash,
            issues=tuple(issues),
        )

    @staticmethod
    def _call_name(function: ast.expr) -> str | None:
        if isinstance(function, ast.Name):
            return function.id
        if isinstance(function, ast.Attribute):
            return function.attr
        return None
