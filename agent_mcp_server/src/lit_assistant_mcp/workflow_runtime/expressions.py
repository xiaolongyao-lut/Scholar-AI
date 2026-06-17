"""Bounded JSON expression evaluator for controlled MCP workflows."""

import json
import re
from string import Formatter
from typing import Any

from ..redaction import SecretRedactor

MAX_MAP_ITEMS: int = 200
REFERENCE_RE = re.compile(r"^\$(steps|input|vars|item)(?:\.|$)")


class SafeFormatDict(dict[str, Any]):
    """Format-map wrapper that leaves unknown placeholders visible."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class ExpressionEvaluator:
    """Evaluate a small, data-only expression subset."""

    def evaluate(self, value: Any, context: dict[str, Any]) -> Any:
        """Evaluate a literal or supported expression.

        Args:
            value: JSON-compatible literal or expression object.
            context: Workflow context containing `steps`, `input`, and `vars`.

        Returns:
            Evaluated JSON-compatible value.
        """
        if isinstance(value, str):
            if REFERENCE_RE.match(value):
                return self._select_reference(value, context)
            return SecretRedactor.scan(value)
        if isinstance(value, list):
            return [self.evaluate(item, context) for item in value]
        if isinstance(value, dict):
            if len(value) == 1:
                key = next(iter(value))
                if key == "$select":
                    return self._op_select(value[key], context)
                if key == "$map":
                    return self._op_map(value[key], context)
                if key == "$filter":
                    return self._op_filter(value[key], context)
                if key == "$groupBy":
                    return self._op_group_by(value[key], context)
                if key == "$join":
                    return self._op_join(value[key], context)
                if key == "$template":
                    return self._op_template(value[key], context)
            return {str(k): self.evaluate(v, context) for k, v in value.items()}
        return value

    def _op_select(self, payload: Any, context: dict[str, Any]) -> Any:
        if isinstance(payload, str):
            return self.evaluate(payload, context)
        if not isinstance(payload, dict):
            raise ValueError("$select must be a string reference or object")
        source = self.evaluate(payload.get("from"), context)
        path = payload.get("path", "")
        if not isinstance(path, str):
            raise ValueError("$select.path must be a string")
        return self._get_path(source, path)

    def _op_map(self, payload: Any, context: dict[str, Any]) -> list[Any]:
        if not isinstance(payload, dict):
            raise ValueError("$map must be an object")
        items = self.evaluate(payload.get("from"), context)
        if not isinstance(items, list):
            raise ValueError("$map.from must evaluate to an array")
        alias = payload.get("as", "item")
        if not isinstance(alias, str) or not alias:
            raise ValueError("$map.as must be a non-empty string")
        template = payload.get("template")
        limit = self._bounded_limit(payload.get("limit", MAX_MAP_ITEMS))
        output: list[Any] = []
        for item in items[:limit]:
            scoped = self._with_var(context, alias, item)
            output.append(self.evaluate(template, scoped))
        return output

    def _op_filter(self, payload: Any, context: dict[str, Any]) -> list[Any]:
        if not isinstance(payload, dict):
            raise ValueError("$filter must be an object")
        items = self.evaluate(payload.get("from"), context)
        if not isinstance(items, list):
            raise ValueError("$filter.from must evaluate to an array")
        alias = payload.get("as", "item")
        if not isinstance(alias, str) or not alias:
            raise ValueError("$filter.as must be a non-empty string")
        where = payload.get("where")
        limit = self._bounded_limit(payload.get("limit", MAX_MAP_ITEMS))
        output: list[Any] = []
        for item in items:
            scoped = self._with_var(context, alias, item)
            if self._predicate(where, scoped):
                output.append(item)
                if len(output) >= limit:
                    break
        return output

    def _op_group_by(self, payload: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("$groupBy must be an object")
        items = self.evaluate(payload.get("from"), context)
        if not isinstance(items, list):
            raise ValueError("$groupBy.from must evaluate to an array")
        key_expr = payload.get("key")
        alias = payload.get("as", "item")
        if not isinstance(alias, str) or not alias:
            raise ValueError("$groupBy.as must be a non-empty string")
        groups: dict[str, list[Any]] = {}
        for item in items[:MAX_MAP_ITEMS]:
            scoped = self._with_var(context, alias, item)
            key = self.evaluate(key_expr, scoped)
            key_text = self._stringify(key)
            groups.setdefault(key_text, []).append(item)
        return [{"key": key, "items": grouped} for key, grouped in groups.items()]

    def _op_join(self, payload: Any, context: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise ValueError("$join must be an object")
        items = self.evaluate(payload.get("items"), context)
        if not isinstance(items, list):
            raise ValueError("$join.items must evaluate to an array")
        separator = payload.get("separator", "\n")
        if not isinstance(separator, str):
            raise ValueError("$join.separator must be a string")
        return SecretRedactor.scan(separator.join(self._stringify(item) for item in items))

    def _op_template(self, payload: Any, context: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise ValueError("$template must be an object")
        template = payload.get("template")
        if not isinstance(template, str):
            raise ValueError("$template.template must be a string")
        vars_payload = payload.get("vars", {})
        if not isinstance(vars_payload, dict):
            raise ValueError("$template.vars must be an object")
        vars_evaluated = {
            str(key): self._stringify(self.evaluate(value, context))
            for key, value in vars_payload.items()
        }
        used_fields = [field_name for _, field_name, _, _ in Formatter().parse(template) if field_name]
        for field_name in used_fields:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name):
                raise ValueError("template placeholders must be simple identifiers")
        rendered = template.format_map(SafeFormatDict(vars_evaluated))
        return SecretRedactor.scan(rendered)

    def _predicate(self, payload: Any, context: dict[str, Any]) -> bool:
        if isinstance(payload, bool):
            return payload
        if isinstance(payload, str) or (isinstance(payload, dict) and any(key.startswith("$") for key in payload)):
            return bool(self.evaluate(payload, context))
        if not isinstance(payload, dict):
            raise ValueError("$filter.where must be a predicate object")
        if "equals" in payload:
            left, right = self._binary_operands(payload["equals"], context)
            return left == right
        if "contains" in payload:
            spec = payload["contains"]
            if not isinstance(spec, dict):
                raise ValueError("contains predicate must be an object")
            haystack = self._stringify(self.evaluate(spec.get("field"), context))
            needle = self._stringify(self.evaluate(spec.get("value"), context))
            case_sensitive = bool(spec.get("case_sensitive", False))
            if not case_sensitive:
                haystack = haystack.lower()
                needle = needle.lower()
            return needle in haystack
        field = payload.get("field")
        op = payload.get("op")
        expected = payload.get("value")
        actual = self.evaluate(field, context)
        expected_value = self.evaluate(expected, context)
        if op == "==":
            return actual == expected_value
        if op == "!=":
            return actual != expected_value
        if op in {">", ">=", "<", "<="}:
            return self._compare(actual, expected_value, op)
        raise ValueError("unsupported predicate operator")

    def _binary_operands(self, payload: Any, context: dict[str, Any]) -> tuple[Any, Any]:
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError("binary predicate must contain exactly two operands")
        return self.evaluate(payload[0], context), self.evaluate(payload[1], context)

    def _compare(self, left: Any, right: Any, op: str) -> bool:
        try:
            left_number = float(left)
            right_number = float(right)
        except (TypeError, ValueError) as exc:
            raise ValueError("comparison operands must be numeric") from exc
        if op == ">":
            return left_number > right_number
        if op == ">=":
            return left_number >= right_number
        if op == "<":
            return left_number < right_number
        return left_number <= right_number

    def _select_reference(self, reference: str, context: dict[str, Any]) -> Any:
        if not isinstance(reference, str) or not reference.startswith("$"):
            raise ValueError("reference must start with $")
        parts = reference[1:].split(".")
        if not parts or parts[0] not in {"steps", "input", "vars", "item"}:
            raise ValueError(f"unsupported reference: {reference}")
        root_name = parts[0]
        if root_name == "item":
            current = context.get("vars", {}).get("item")
        else:
            current = context.get(root_name)
        return self._get_path(current, ".".join(parts[1:]))

    def _get_path(self, value: Any, path: str) -> Any:
        if path == "":
            return value
        current = value
        for part in path.split("."):
            if part == "":
                raise ValueError("path segments must be non-empty")
            if isinstance(current, list):
                try:
                    index = int(part)
                except ValueError as exc:
                    raise ValueError("array path segment must be an integer") from exc
                if index < 0 or index >= len(current):
                    return None
                current = current[index]
                continue
            if isinstance(current, dict):
                current = current.get(part)
                continue
            return None
        return current

    def _with_var(self, context: dict[str, Any], alias: str, value: Any) -> dict[str, Any]:
        scoped = {
            "steps": context.get("steps", {}),
            "input": context.get("input", {}),
            "vars": dict(context.get("vars", {})),
        }
        scoped["vars"][alias] = value
        if alias == "item":
            scoped["item"] = value
        return scoped

    def _bounded_limit(self, value: Any) -> int:
        if not isinstance(value, int):
            raise ValueError("limit must be an integer")
        if value < 1 or value > MAX_MAP_ITEMS:
            raise ValueError(f"limit must be between 1 and {MAX_MAP_ITEMS}")
        return value

    def _stringify(self, value: Any) -> str:
        if isinstance(value, str):
            return SecretRedactor.scan(value)
        if value is None:
            return ""
        return SecretRedactor.scan(json.dumps(value, ensure_ascii=False, sort_keys=True))
