import argparse
import json
import re
from pathlib import Path


BLOCKED = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|PRAGMA|REPLACE|ATTACH|DETACH)\b", re.I)


def strip_markdown(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def split_statements(sql):
    parts = [part.strip() for part in sql.strip().split(";") if part.strip()]
    return parts


def schema_tables(schema_path):
    if not schema_path:
        return None
    path = Path(schema_path)
    if not path.exists():
        return None
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        tables = data.get("tables", {})
        if isinstance(tables, dict):
            return set(tables)
        if isinstance(tables, list):
            return {str(item.get("table_name", item)) for item in tables}
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"CREATE\s+TABLE\s+([A-Za-z_][\w]*)", text, flags=re.I))


def referenced_tables(sql):
    names = set()
    for _, name in re.findall(r"\b(FROM|JOIN)\s+([A-Za-z_][\w]*)", sql, flags=re.I):
        names.add(name)
    return names


def validate_sql(sql, known_tables=None):
    normalized = strip_markdown(sql)
    if not normalized:
        return {"is_valid": False, "reason": "empty_sql", "join_count": 0, "normalized_sql": normalized}
    statements = split_statements(normalized)
    if len(statements) != 1:
        return {"is_valid": False, "reason": "multiple_or_empty_statements", "join_count": 0, "normalized_sql": normalized}
    statement = statements[0]
    if not re.match(r"^\s*SELECT\b", statement, flags=re.I):
        return {"is_valid": False, "reason": "not_select_only", "join_count": 0, "normalized_sql": statement}
    if BLOCKED.search(statement):
        return {"is_valid": False, "reason": "blocked_keyword", "join_count": 0, "normalized_sql": statement}
    if known_tables is not None:
        unknown = sorted(referenced_tables(statement) - set(known_tables))
        if unknown:
            return {
                "is_valid": False,
                "reason": f"unknown_tables:{','.join(unknown)}",
                "join_count": len(re.findall(r"\bJOIN\b", statement, flags=re.I)),
                "normalized_sql": statement,
            }
    return {
        "is_valid": True,
        "reason": "ok",
        "join_count": len(re.findall(r"\bJOIN\b", statement, flags=re.I)),
        "normalized_sql": statement,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql", required=True)
    parser.add_argument("--schema_path")
    args = parser.parse_args()
    print(json.dumps(validate_sql(args.sql, schema_tables(args.schema_path)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
