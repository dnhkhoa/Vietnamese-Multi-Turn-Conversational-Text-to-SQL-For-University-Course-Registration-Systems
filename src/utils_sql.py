import sqlglot
from sqlglot import exp


def normalize_sql(sql):
    """
    Chuẩn hóa SQL để dễ lưu và so sánh.
    """
    try:
        return sqlglot.parse_one(sql).sql()
    except Exception:
        return sql.strip()


def split_and_conditions(expr):
    """
    Tách WHERE a AND b AND c thành [a, b, c].
    """
    if isinstance(expr, exp.And):
        return split_and_conditions(expr.left) + split_and_conditions(expr.right)
    return [expr.sql()]


def parse_simple_sql(sql):
    """
    Parse SQL đơn giản thành:
    - SELECT columns
    - FROM table
    - WHERE conditions
    - ORDER BY
    - LIMIT
    """
    tree = sqlglot.parse_one(sql)

    # SELECT columns
    select_exprs = []
    for e in tree.expressions:
        select_exprs.append(e.sql())

    # FROM table
    from_expr = tree.args.get("from") or tree.args.get("from_")
    table_name = None

    if from_expr:
        tables = list(from_expr.find_all(exp.Table))
        if tables:
            table_name = tables[0].sql()

    # fallback: tìm table trong toàn bộ cây SQL
    if not table_name:
        tables = list(tree.find_all(exp.Table))
        if tables:
            table_name = tables[0].sql()

    # WHERE conditions
    where_expr = tree.args.get("where")
    conditions = []

    if where_expr:
        condition_root = where_expr.this
        conditions = split_and_conditions(condition_root)

    # ORDER BY
    order_expr = tree.args.get("order")
    order_by = []

    if order_expr:
        for ordered in order_expr.expressions:
            direction = "DESC" if ordered.args.get("desc") else "ASC"
            order_by.append({
                "column": ordered.this.sql(),
                "direction": direction
            })

    # LIMIT
    limit_expr = tree.args.get("limit")
    limit_value = None

    if limit_expr:
        if limit_expr.expression:
            limit_value = limit_expr.expression.sql()
        elif limit_expr.this:
            limit_value = limit_expr.this.sql()

    return {
        "select": select_exprs,
        "from": table_name,
        "where": conditions,
        "order_by": order_by,
        "limit": limit_value
    }


def build_sql(select_cols, table_name, conditions=None, order_by=None, limit=None):
    """
    Build lại SQL từ các thành phần đã parse.
    """
    conditions = conditions or []
    order_by = order_by or []

    select_part = ", ".join(select_cols) if select_cols else "*"

    sql = f"SELECT {select_part} FROM {table_name}"

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    if order_by:
        order_parts = []
        for item in order_by:
            order_parts.append(f"{item['column']} {item['direction']}")
        sql += " ORDER BY " + ", ".join(order_parts)

    if limit:
        sql += f" LIMIT {limit}"

    return normalize_sql(sql)