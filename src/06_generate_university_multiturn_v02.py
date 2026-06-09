import json
import random
import re
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "data" / "processed" / "university_v02"
SCHEMA_DIR = OUT_DIR / "schema"
DB_DIR = OUT_DIR / "database"
CONV_DIR = OUT_DIR / "conversation"
TRAINING_DIR = OUT_DIR / "training"

DB_ID = "university_registration"
DB_PATH = DB_DIR / f"{DB_ID}.sqlite"

SPLIT_COUNTS = {
    "train": 500,
    "dev": 75,
    "test": 75,
}

RANDOM_SEED = 24052026

DEPARTMENTS = [
    (1, "Công nghệ thông tin"),
    (2, "Khoa học dữ liệu"),
    (3, "Kinh tế"),
    (4, "Điện tử viễn thông"),
    (5, "Ngoại ngữ"),
]

MAJORS = [
    (1, "Khoa học máy tính", 1),
    (2, "Trí tuệ nhân tạo", 1),
    (3, "Kỹ thuật phần mềm", 1),
    (4, "Khoa học dữ liệu", 2),
    (5, "Phân tích kinh doanh", 2),
    (6, "Tài chính", 3),
    (7, "Marketing", 3),
    (8, "Mạng máy tính", 4),
    (9, "Hệ thống nhúng", 4),
    (10, "Ngôn ngữ Anh", 5),
]

COURSES = [
    (1, "DB101", "Cơ sở dữ liệu", 3, 1),
    (2, "AI201", "Nhập môn trí tuệ nhân tạo", 3, 1),
    (3, "ML301", "Học máy", 3, 2),
    (4, "DS201", "Khai phá dữ liệu", 3, 2),
    (5, "SE101", "Nhập môn kỹ thuật phần mềm", 3, 1),
    (6, "WEB202", "Phát triển ứng dụng web", 3, 1),
    (7, "STAT101", "Xác suất thống kê", 3, 2),
    (8, "ALG101", "Cấu trúc dữ liệu", 4, 1),
    (9, "NET201", "Mạng máy tính", 3, 4),
    (10, "OS201", "Hệ điều hành", 3, 1),
    (11, "FIN101", "Tài chính doanh nghiệp", 3, 3),
    (12, "MKT101", "Nguyên lý marketing", 3, 3),
    (13, "IOT201", "Internet vạn vật", 3, 4),
    (14, "ENG101", "Tiếng Anh học thuật", 2, 5),
    (15, "NLP301", "Xử lý ngôn ngữ tự nhiên", 3, 2),
    (16, "BI201", "Kho dữ liệu và BI", 3, 2),
]

PREREQUISITES = [
    (1, 8), (2, 8), (3, 2), (4, 7), (6, 5), (9, 8), (10, 8),
    (13, 9), (15, 3), (16, 1), (16, 7),
]

SEMESTERS = [
    (1, "2023-1", 2023, "1"),
    (2, "2023-2", 2023, "2"),
    (3, "2024-1", 2024, "1"),
    (4, "2024-2", 2024, "2"),
    (5, "2025-1", 2025, "1"),
]

COURSE_BY_ID = {course[0]: course for course in COURSES}
COURSE_BY_NAME = {course[2]: course for course in COURSES}
DEPARTMENT_BY_ID = {department[0]: department for department in DEPARTMENTS}

FIRST_NAMES = [
    "An", "Bình", "Chi", "Dũng", "Giang", "Hà", "Hải", "Hạnh", "Huy",
    "Khánh", "Lan", "Linh", "Long", "Mai", "Minh", "Nam", "Ngân",
    "Phúc", "Quân", "Thảo", "Trang", "Trí", "Tuấn", "Vy", "Yến",
]

LAST_NAMES = [
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi",
    "Đỗ", "Hồ", "Ngô", "Dương", "Lý",
]

SCHEDULES = [
    "Thứ 2 07:30", "Thứ 2 13:30", "Thứ 3 09:30", "Thứ 3 15:30",
    "Thứ 4 07:30", "Thứ 4 13:30", "Thứ 5 09:30", "Thứ 6 15:30",
]


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


def sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return q(value)
    return str(value)


def insert_statement(table_name, row):
    values = ", ".join(sql_literal(value) for value in row)
    return f"INSERT INTO {table_name} VALUES ({values});"


def build_seed_data_sql(table_rows):
    lines = [
        "PRAGMA foreign_keys=OFF;",
        "BEGIN TRANSACTION;",
    ]
    for table_name, rows in table_rows:
        lines.append(f"-- {table_name}")
        lines.extend(insert_statement(table_name, row) for row in rows)
    lines.extend([
        "COMMIT;",
        "PRAGMA foreign_keys=ON;",
    ])
    return "\n".join(lines)


def department_name_for_course(course_name):
    course = COURSE_BY_NAME[course_name]
    return DEPARTMENT_BY_ID[course[4]][1]


def prerequisite_department_options():
    options = []
    for course_id, prerequisite_course_id in PREREQUISITES:
        course = COURSE_BY_ID[course_id]
        prerequisite = COURSE_BY_ID[prerequisite_course_id]
        department_name = DEPARTMENT_BY_ID[course[4]][1]
        options.append((prerequisite[2], department_name))
    return options


def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


TAG_GROUPS = {
    "context": {"coreference", "contextual_filter"},
    "sql_clause": {
        "aggregate",
        "group_by",
        "having",
        "join",
        "join_expand",
        "limit",
        "order_by",
        "self_join",
        "subquery",
    },
    "edit": {"add_filter", "remove_filter", "replace"},
}


def group_tags(tags):
    grouped = {group: [] for group in TAG_GROUPS}
    grouped["other"] = []
    for tag in tags:
        matched = False
        for group, group_tags_set in TAG_GROUPS.items():
            if tag in group_tags_set:
                grouped[group].append(tag)
                matched = True
                break
        if not matched:
            grouped["other"].append(tag)
    return {group: values for group, values in grouped.items() if values}


def build_schema_sql():
    return """
CREATE TABLE departments (
  department_id INTEGER PRIMARY KEY,
  department_name TEXT NOT NULL
);

CREATE TABLE majors (
  major_id INTEGER PRIMARY KEY,
  major_name TEXT NOT NULL,
  department_id INTEGER NOT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE students (
  student_id INTEGER PRIMARY KEY,
  full_name TEXT NOT NULL,
  cohort_year INTEGER NOT NULL,
  gender TEXT NOT NULL,
  major_id INTEGER NOT NULL,
  gpa REAL NOT NULL,
  FOREIGN KEY (major_id) REFERENCES majors(major_id)
);

CREATE TABLE instructors (
  instructor_id INTEGER PRIMARY KEY,
  full_name TEXT NOT NULL,
  department_id INTEGER NOT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE courses (
  course_id INTEGER PRIMARY KEY,
  course_code TEXT NOT NULL,
  course_name TEXT NOT NULL,
  credits INTEGER NOT NULL,
  department_id INTEGER NOT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE semesters (
  semester_id INTEGER PRIMARY KEY,
  semester_name TEXT NOT NULL,
  academic_year INTEGER NOT NULL,
  term TEXT NOT NULL
);

CREATE TABLE course_sections (
  section_id INTEGER PRIMARY KEY,
  section_code TEXT NOT NULL,
  course_id INTEGER NOT NULL,
  semester_id INTEGER NOT NULL,
  instructor_id INTEGER NOT NULL,
  room TEXT NOT NULL,
  capacity INTEGER NOT NULL,
  schedule TEXT NOT NULL,
  FOREIGN KEY (course_id) REFERENCES courses(course_id),
  FOREIGN KEY (semester_id) REFERENCES semesters(semester_id),
  FOREIGN KEY (instructor_id) REFERENCES instructors(instructor_id)
);

CREATE TABLE enrollments (
  enrollment_id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL,
  section_id INTEGER NOT NULL,
  status TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  grade TEXT,
  FOREIGN KEY (student_id) REFERENCES students(student_id),
  FOREIGN KEY (section_id) REFERENCES course_sections(section_id)
);

CREATE TABLE prerequisites (
  course_id INTEGER NOT NULL,
  prerequisite_course_id INTEGER NOT NULL,
  PRIMARY KEY (course_id, prerequisite_course_id),
  FOREIGN KEY (course_id) REFERENCES courses(course_id),
  FOREIGN KEY (prerequisite_course_id) REFERENCES courses(course_id)
);

CREATE TABLE waitlists (
  waitlist_id INTEGER PRIMARY KEY,
  student_id INTEGER NOT NULL,
  section_id INTEGER NOT NULL,
  priority INTEGER NOT NULL,
  status TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  FOREIGN KEY (student_id) REFERENCES students(student_id),
  FOREIGN KEY (section_id) REFERENCES course_sections(section_id)
);

CREATE INDEX idx_departments_name ON departments(department_name);
CREATE INDEX idx_majors_name ON majors(major_name);
CREATE INDEX idx_students_major ON students(major_id);
CREATE INDEX idx_students_cohort ON students(cohort_year);
CREATE INDEX idx_courses_name ON courses(course_name);
CREATE INDEX idx_courses_department ON courses(department_id);
CREATE INDEX idx_semesters_name ON semesters(semester_name);
CREATE INDEX idx_sections_course_semester ON course_sections(course_id, semester_id);
CREATE INDEX idx_sections_instructor ON course_sections(instructor_id);
CREATE INDEX idx_sections_schedule ON course_sections(schedule);
CREATE INDEX idx_enrollments_section_status ON enrollments(section_id, status);
CREATE INDEX idx_enrollments_student_status ON enrollments(student_id, status);
CREATE INDEX idx_waitlists_section_status ON waitlists(section_id, status);
CREATE INDEX idx_waitlists_student_status ON waitlists(student_id, status);
CREATE INDEX idx_prerequisites_course ON prerequisites(course_id);
CREATE INDEX idx_prerequisites_prerequisite ON prerequisites(prerequisite_course_id);
""".strip()


def build_schema_metadata():
    return {
        "db_id": DB_ID,
        "description": "Synthetic university course registration schema for multi-turn Text-to-SQL.",
        "tables": {
            "departments": ["department_id", "department_name"],
            "majors": ["major_id", "major_name", "department_id"],
            "students": ["student_id", "full_name", "cohort_year", "gender", "major_id", "gpa"],
            "instructors": ["instructor_id", "full_name", "department_id"],
            "courses": ["course_id", "course_code", "course_name", "credits", "department_id"],
            "semesters": ["semester_id", "semester_name", "academic_year", "term"],
            "course_sections": [
                "section_id", "section_code", "course_id", "semester_id",
                "instructor_id", "room", "capacity", "schedule",
            ],
            "enrollments": ["enrollment_id", "student_id", "section_id", "status", "registered_at", "grade"],
            "prerequisites": ["course_id", "prerequisite_course_id"],
            "waitlists": ["waitlist_id", "student_id", "section_id", "priority", "status", "requested_at"],
        },
        "foreign_keys": [
            ["majors.department_id", "departments.department_id"],
            ["students.major_id", "majors.major_id"],
            ["instructors.department_id", "departments.department_id"],
            ["courses.department_id", "departments.department_id"],
            ["course_sections.course_id", "courses.course_id"],
            ["course_sections.semester_id", "semesters.semester_id"],
            ["course_sections.instructor_id", "instructors.instructor_id"],
            ["enrollments.student_id", "students.student_id"],
            ["enrollments.section_id", "course_sections.section_id"],
            ["prerequisites.course_id", "courses.course_id"],
            ["prerequisites.prerequisite_course_id", "courses.course_id"],
            ["waitlists.student_id", "students.student_id"],
            ["waitlists.section_id", "course_sections.section_id"],
        ],
    }


def build_tables_json():
    metadata = build_schema_metadata()
    table_names = list(metadata["tables"])
    column_names = [[-1, "*"]]
    column_names_original = [[-1, "*"]]
    column_types = ["text"]
    primary_keys = []

    explicit_primary_keys = {
        "departments.department_id",
        "majors.major_id",
        "students.student_id",
        "instructors.instructor_id",
        "courses.course_id",
        "semesters.semester_id",
        "course_sections.section_id",
        "enrollments.enrollment_id",
        "prerequisites.course_id",
        "prerequisites.prerequisite_course_id",
        "waitlists.waitlist_id",
    }

    numeric_columns = {
        "academic_year",
        "capacity",
        "cohort_year",
        "credits",
        "gpa",
        "priority",
    }

    for table_index, table_name in enumerate(table_names):
        for column_name in metadata["tables"][table_name]:
            qualified = f"{table_name}.{column_name}"
            column_names.append([table_index, column_name])
            column_names_original.append([table_index, column_name])
            if column_name.endswith("_id") or column_name in numeric_columns:
                column_types.append("number")
            else:
                column_types.append("text")
            if qualified in explicit_primary_keys:
                primary_keys.append(len(column_names) - 1)

    column_lookup = {
        f"{table_names[table_index]}.{column_name}": index
        for index, (table_index, column_name) in enumerate(column_names)
        if table_index >= 0
    }
    foreign_keys = [
        [column_lookup[left], column_lookup[right]]
        for left, right in metadata["foreign_keys"]
        if left in column_lookup and right in column_lookup
    ]

    return [{
        "db_id": DB_ID,
        "table_names": table_names,
        "table_names_original": table_names,
        "column_names": column_names,
        "column_names_original": column_names_original,
        "column_types": column_types,
        "primary_keys": primary_keys,
        "foreign_keys": foreign_keys,
    }]


def schema_prompt():
    metadata = build_schema_metadata()
    lines = []
    for table, columns in metadata["tables"].items():
        lines.append(f"{table}({', '.join(columns)})")
    lines.append("Foreign keys:")
    for left, right in metadata["foreign_keys"]:
        lines.append(f"{left} -> {right}")
    return "\n".join(lines)


def create_database():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(build_schema_sql())
    rng = random.Random(RANDOM_SEED)

    conn.executemany("INSERT INTO departments VALUES (?, ?)", DEPARTMENTS)
    conn.executemany("INSERT INTO majors VALUES (?, ?, ?)", MAJORS)
    conn.executemany("INSERT INTO courses VALUES (?, ?, ?, ?, ?)", COURSES)
    conn.executemany("INSERT INTO semesters VALUES (?, ?, ?, ?)", SEMESTERS)

    instructors = []
    instructor_id = 1
    for department_id, department_name in DEPARTMENTS:
        for idx in range(1, 7):
            name = f"{rng.choice(LAST_NAMES)} {rng.choice(FIRST_NAMES)}"
            instructors.append((instructor_id, f"GV {name} {department_name.split()[0]} {idx}", department_id))
            instructor_id += 1
    conn.executemany("INSERT INTO instructors VALUES (?, ?, ?)", instructors)

    students = []
    for student_id in range(1, 901):
        major_id, major_name, _ = rng.choice(MAJORS)
        name = f"{rng.choice(LAST_NAMES)} {rng.choice(FIRST_NAMES)} {student_id:03d}"
        cohort_year = rng.choice([2021, 2022, 2023, 2024, 2025])
        gender = rng.choice(["Nam", "Nữ"])
        gpa = round(rng.uniform(2.0, 4.0), 2)
        students.append((student_id, name, cohort_year, gender, major_id, gpa))
    conn.executemany("INSERT INTO students VALUES (?, ?, ?, ?, ?, ?)", students)

    instructors_by_department = {}
    for instructor in instructors:
        instructors_by_department.setdefault(instructor[2], []).append(instructor[0])

    sections = []
    section_id = 1
    for semester_id, semester_name, _, _ in SEMESTERS:
        for course_id, course_code, _, _, department_id in COURSES:
            for section_no in range(1, 6):
                instructor_id = rng.choice(instructors_by_department[department_id])
                capacity = rng.choice([35, 45, 50, 60, 70])
                room = f"{rng.choice(['A', 'B', 'C', 'D'])}{rng.randint(101, 509)}"
                schedule = SCHEDULES[section_no - 1]
                section_code = f"{course_code}-{semester_name}-{section_no}"
                sections.append((
                    section_id, section_code, course_id, semester_id,
                    instructor_id, room, capacity, schedule,
                ))
                section_id += 1
    conn.executemany("INSERT INTO course_sections VALUES (?, ?, ?, ?, ?, ?, ?, ?)", sections)

    enrollments = []
    enrollment_id = 1
    grades = ["A", "B+", "B", "C+", "C", "D", None]
    student_ids = [row[0] for row in students]
    for section in sections:
        _, _, _, semester_id, _, _, capacity, _ = section
        target = rng.randint(max(18, capacity - 15), capacity + 18)
        for student_id in rng.sample(student_ids, min(target, len(student_ids))):
            status_roll = rng.random()
            if status_roll < 0.70:
                status = "enrolled"
            elif status_roll < 0.90:
                status = "completed"
            else:
                status = "dropped"
            month = min(12, 1 + semester_id * 2)
            registered_at = f"202{2 + semester_id}-{month:02d}-{rng.randint(1, 28):02d}"
            grade = rng.choice(grades)
            enrollments.append((enrollment_id, student_id, section[0], status, registered_at, grade))
            enrollment_id += 1
    conn.executemany("INSERT INTO enrollments VALUES (?, ?, ?, ?, ?, ?)", enrollments)

    conn.executemany("INSERT INTO prerequisites VALUES (?, ?)", PREREQUISITES)

    waitlists = []
    waitlist_id = 1
    for section in sections:
        wait_count = rng.randint(3, 18)
        for priority, student_id in enumerate(rng.sample(student_ids, wait_count), start=1):
            status = "waiting" if rng.random() < 0.82 else "removed"
            requested_at = f"2025-01-{rng.randint(1, 28):02d}"
            waitlists.append((waitlist_id, student_id, section[0], priority, status, requested_at))
            waitlist_id += 1
    conn.executemany("INSERT INTO waitlists VALUES (?, ?, ?, ?, ?, ?)", waitlists)

    conn.commit()
    conn.close()
    return build_seed_data_sql([
        ("departments", DEPARTMENTS),
        ("majors", MAJORS),
        ("courses", COURSES),
        ("semesters", SEMESTERS),
        ("instructors", instructors),
        ("students", students),
        ("course_sections", sections),
        ("enrollments", enrollments),
        ("prerequisites", PREREQUISITES),
        ("waitlists", waitlists),
    ])


def turn(turn_id, utterance, sql, operation, tags):
    if operation == "filter_replace" and {"remove_filter", "add_filter"}.issubset(tags):
        operation = "filter_remove_add"
    return {
        "turn_id": turn_id,
        "utterance": utterance,
        "sql": one_line(sql),
        "operation": operation,
        "tags": tags,
        "tag_groups": group_tags(tags),
    }


def one_line(sql):
    return re.sub(r"\s+", " ", sql).strip()


def pick_values(rng):
    course = rng.choice(COURSES)
    course2 = rng.choice([c for c in COURSES if c[0] != course[0]])
    prereq = rng.choice(["Cấu trúc dữ liệu", "Xác suất thống kê", "Nhập môn trí tuệ nhân tạo", "Cơ sở dữ liệu"])
    major = rng.choice(MAJORS)
    major2 = rng.choice([m for m in MAJORS if m[0] != major[0]])
    department = rng.choice(DEPARTMENTS)
    department2 = rng.choice([d for d in DEPARTMENTS if d[0] != department[0]])
    semester = rng.choice(SEMESTERS)
    semester2 = rng.choice([s for s in SEMESTERS if s[0] != semester[0]])
    return {
        "course": course[2],
        "course2": course2[2],
        "credits": course[3],
        "prereq": prereq,
        "major": major[1],
        "major2": major2[1],
        "department": department[1],
        "department2": department2[1],
        "semester": semester[1],
        "semester2": semester2[1],
        "cohort": rng.choice([2021, 2022, 2023, 2024, 2025]),
        "min_count": rng.choice([1, 2, 3, 5, 8]),
        "min_sections": rng.choice([1, 2, 3]),
        "limit": rng.choice([5, 10, 15]),
        "day": rng.choice(["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6"]),
        "day2": rng.choice(["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6"]),
    }


def scenario_student_filter(conv_id, split, rng):
    v = pick_values(rng)
    base_from = f"""
FROM students s
JOIN majors m ON s.major_id = m.major_id
JOIN enrollments e ON s.student_id = e.student_id
JOIN course_sections cs ON e.section_id = cs.section_id
JOIN courses c ON cs.course_id = c.course_id
JOIN semesters sem ON cs.semester_id = sem.semester_id
WHERE c.course_name = {q(v['course'])}
  AND sem.semester_name = {q(v['semester'])}
  AND e.status = 'enrolled'
"""
    sql1 = f"SELECT DISTINCT s.student_id, s.full_name, m.major_name, s.cohort_year, s.gpa {base_from}"
    sql2 = sql1 + f" AND m.major_name = {q(v['major'])}"
    sql3 = sql1 + f" AND m.major_name = {q(v['major2'])}"
    sql4 = sql1 + f" AND s.cohort_year = {v['cohort']}"
    sql5 = f"""
SELECT DISTINCT s.student_id, s.full_name, cs.section_code, i.full_name AS instructor_name
FROM students s
JOIN enrollments e ON s.student_id = e.student_id
JOIN course_sections cs ON e.section_id = cs.section_id
JOIN instructors i ON cs.instructor_id = i.instructor_id
JOIN courses c ON cs.course_id = c.course_id
JOIN semesters sem ON cs.semester_id = sem.semester_id
WHERE c.course_name = {q(v['course'])}
  AND sem.semester_name = {q(v['semester'])}
  AND e.status = 'enrolled'
  AND s.cohort_year = {v['cohort']}
"""
    sql6 = sql5 + " ORDER BY s.full_name ASC"
    return make_conversation(conv_id, split, [
        turn(1, f"Cho tôi danh sách sinh viên đã đăng ký môn {v['course']} trong học kỳ {v['semester']}.", sql1, "initial_query", ["join"]),
        turn(2, f"Chỉ lấy những bạn thuộc ngành {v['major']}.", sql2, "filter_add", ["contextual_filter"]),
        turn(3, f"Đổi sang ngành {v['major2']}.", sql3, "filter_replace", ["contextual_filter", "replace"]),
        turn(4, f"Bỏ điều kiện ngành đi, chỉ xem khóa {v['cohort']}.", sql4, "filter_replace", ["remove_filter", "add_filter"]),
        turn(5, "Những sinh viên đó đang học ở lớp nào và với giảng viên nào?", sql5, "join_expand", ["coreference", "join"]),
        turn(6, "Sắp xếp theo tên sinh viên để dễ đối chiếu.", sql6, "order_add", ["order_by"]),
    ])


def scenario_group_by_major(conv_id, split, rng):
    v = pick_values(rng)
    threshold = rng.choice([1, 2, 3, 5])
    def sql(course, extra_where="", having="", order="", limit=""):
        return f"""
SELECT m.major_name, COUNT(DISTINCT s.student_id) AS student_count
FROM students s
JOIN majors m ON s.major_id = m.major_id
JOIN enrollments e ON s.student_id = e.student_id
JOIN course_sections cs ON e.section_id = cs.section_id
JOIN courses c ON cs.course_id = c.course_id
JOIN semesters sem ON cs.semester_id = sem.semester_id
WHERE c.course_name = {q(course)}
  AND sem.semester_name = {q(v['semester'])}
  AND e.status = 'enrolled'
  {extra_where}
GROUP BY m.major_name
{having}
{order}
{limit}
"""

    return make_conversation(conv_id, split, [
        turn(1, f"Mỗi ngành có bao nhiêu sinh viên đăng ký môn {v['course']} trong học kỳ {v['semester']}?", sql(v["course"]), "aggregate_group_by", ["join", "group_by", "aggregate"]),
        turn(2, f"Chỉ tính sinh viên khóa {v['cohort']}.", sql(v["course"], f"AND s.cohort_year = {v['cohort']}"), "filter_add", ["contextual_filter"]),
        turn(3, f"Còn môn {v['course2']} thì sao?", sql(v["course2"], f"AND s.cohort_year = {v['cohort']}"), "filter_replace", ["coreference", "replace"]),
        turn(4, f"Chỉ giữ các ngành có ít nhất {threshold} sinh viên.", sql(v["course2"], f"AND s.cohort_year = {v['cohort']}", f"HAVING COUNT(DISTINCT s.student_id) >= {threshold}"), "having_add", ["having"]),
        turn(5, "Sắp xếp ngành đông sinh viên nhất lên trước.", sql(v["course2"], f"AND s.cohort_year = {v['cohort']}", f"HAVING COUNT(DISTINCT s.student_id) >= {threshold}", "ORDER BY student_count DESC"), "order_add", ["order_by"]),
        turn(6, f"Lấy {v['limit']} ngành đầu thôi.", sql(v["course2"], f"AND s.cohort_year = {v['cohort']}", f"HAVING COUNT(DISTINCT s.student_id) >= {threshold}", "ORDER BY student_count DESC", f"LIMIT {v['limit']}"), "limit_add", ["limit"]),
    ])


def scenario_available_sections(conv_id, split, rng):
    v = pick_values(rng)
    v["department"] = department_name_for_course(v["course"])
    v["credits"] = COURSE_BY_NAME[v["course"]][3]
    def sql(extra_join="", extra_where="", order="", limit=""):
        return f"""
SELECT c.course_name, cs.section_code, cs.capacity,
       COUNT(e.enrollment_id) AS enrolled_count,
       cs.capacity - COUNT(e.enrollment_id) AS seats_left
FROM course_sections cs
JOIN courses c ON cs.course_id = c.course_id
JOIN semesters sem ON cs.semester_id = sem.semester_id
{extra_join}
LEFT JOIN enrollments e ON cs.section_id = e.section_id AND e.status = 'enrolled'
WHERE sem.semester_name = {q(v['semester'])}
  {extra_where}
GROUP BY c.course_name, cs.section_code, cs.capacity
HAVING COUNT(e.enrollment_id) < cs.capacity
{order}
{limit}
"""
    dept_join = "JOIN departments d ON c.department_id = d.department_id"
    dept_where = f"AND d.department_name = {q(v['department'])}"
    credit_where = f"{dept_where} AND c.credits = {v['credits']}"
    return make_conversation(conv_id, split, [
        turn(1, f"Học kỳ {v['semester']} còn những lớp học phần nào chưa đầy?", sql(), "aggregate_group_by", ["join", "group_by", "having"]),
        turn(2, f"Chỉ xem các môn của khoa {v['department']}.", sql(dept_join, dept_where), "filter_add", ["contextual_filter"]),
        turn(3, f"Trong số đó, chỉ lấy môn {v['credits']} tín chỉ.", sql(dept_join, credit_where), "filter_add", ["coreference"]),
        turn(4, "Ưu tiên lớp còn nhiều chỗ nhất.", sql(dept_join, credit_where, "ORDER BY seats_left DESC"), "order_add", ["order_by"]),
        turn(5, f"Lấy {v['limit']} lớp thôi.", sql(dept_join, credit_where, "ORDER BY seats_left DESC", f"LIMIT {v['limit']}"), "limit_add", ["limit"]),
    ])


def scenario_waitlist(conv_id, split, rng):
    v = pick_values(rng)
    threshold = rng.choice([1, 2, 3])
    base = f"""
FROM waitlists w
JOIN students s ON w.student_id = s.student_id
JOIN majors m ON s.major_id = m.major_id
JOIN course_sections cs ON w.section_id = cs.section_id
JOIN courses c ON cs.course_id = c.course_id
JOIN semesters sem ON cs.semester_id = sem.semester_id
WHERE c.course_name = {{course}}
  AND sem.semester_name = {q(v['semester'])}
  AND w.status = 'waiting'
"""
    sql1 = f"SELECT s.student_id, s.full_name, c.course_name, cs.section_code, w.priority {base.format(course=q(v['course']))}"
    sql2 = sql1 + f" AND m.major_name = {q(v['major'])}"
    sql3 = f"SELECT s.student_id, s.full_name, c.course_name, cs.section_code, w.priority {base.format(course=q(v['course2']))} AND m.major_name = {q(v['major'])}"
    sql4 = f"""
SELECT cs.section_code, COUNT(w.waitlist_id) AS waitlist_count
{base.format(course=q(v['course2']))}
  AND m.major_name = {q(v['major'])}
GROUP BY cs.section_code
"""
    sql5 = sql4 + f" HAVING COUNT(w.waitlist_id) > {threshold}"
    sql6 = sql5 + " ORDER BY waitlist_count DESC"
    return make_conversation(conv_id, split, [
        turn(1, f"Danh sách sinh viên đang chờ vào môn {v['course']} ở học kỳ {v['semester']} gồm những ai?", sql1, "initial_query", ["join"]),
        turn(2, f"Trong số đó, chỉ lấy sinh viên ngành {v['major']}.", sql2, "filter_add", ["coreference"]),
        turn(3, f"Đổi sang môn {v['course2']}.", sql3, "filter_replace", ["replace"]),
        turn(4, "Đếm theo từng lớp học phần.", sql4, "aggregate_group_by", ["group_by", "aggregate"]),
        turn(5, f"Chỉ hiện lớp có hơn {threshold} bạn đang chờ.", sql5, "having_add", ["having"]),
        turn(6, "Xếp lớp có hàng chờ dài nhất lên trước.", sql6, "order_add", ["order_by"]),
    ])


def scenario_instructor_workload(conv_id, split, rng):
    v = pick_values(rng)
    def sql(extra_join="", extra_where="", having="", order="", limit=""):
        return f"""
SELECT i.full_name AS instructor_name, COUNT(DISTINCT cs.section_id) AS section_count
FROM instructors i
JOIN course_sections cs ON i.instructor_id = cs.instructor_id
JOIN semesters sem ON cs.semester_id = sem.semester_id
{extra_join}
WHERE sem.semester_name = {q(v['semester'])}
  {extra_where}
GROUP BY i.instructor_id, i.full_name
{having}
{order}
{limit}
"""
    dept_join = "JOIN departments d ON i.department_id = d.department_id"
    active_join = dept_join + "\nJOIN enrollments e ON cs.section_id = e.section_id AND e.status = 'enrolled'"
    dept_where = f"AND d.department_name = {q(v['department'])}"
    return make_conversation(conv_id, split, [
        turn(1, f"Mỗi giảng viên đang phụ trách bao nhiêu lớp trong học kỳ {v['semester']}?", sql(), "aggregate_group_by", ["join", "group_by", "aggregate"]),
        turn(2, f"Chỉ tính giảng viên của khoa {v['department']}.", sql(dept_join, dept_where), "filter_add", ["contextual_filter"]),
        turn(3, "Chỉ tính các lớp đã có sinh viên đăng ký.", sql(active_join, dept_where), "filter_add", ["coreference", "join_expand"]),
        turn(4, f"Chỉ giữ giảng viên phụ trách từ {v['min_sections']} lớp trở lên.", sql(active_join, dept_where, f"HAVING COUNT(DISTINCT cs.section_id) >= {v['min_sections']}"), "having_add", ["having"]),
        turn(5, "Sắp xếp người dạy nhiều lớp nhất trước.", sql(active_join, dept_where, f"HAVING COUNT(DISTINCT cs.section_id) >= {v['min_sections']}", "ORDER BY section_count DESC"), "order_add", ["order_by"]),
        turn(6, f"Cho tôi {v['limit']} người đầu tiên.", sql(active_join, dept_where, f"HAVING COUNT(DISTINCT cs.section_id) >= {v['min_sections']}", "ORDER BY section_count DESC", f"LIMIT {v['limit']}"), "limit_add", ["limit"]),
    ])


def scenario_prerequisites(conv_id, split, rng):
    v = pick_values(rng)
    v["prereq"], v["department"] = rng.choice(prerequisite_department_options())
    threshold = rng.choice([1, 2, 3])
    def sql(extra_join="", extra_where="", select_open=False, having="", order=""):
        if select_open:
            select = "SELECT c.course_code, c.course_name, COUNT(DISTINCT cs.section_id) AS open_section_count"
            join_open = f"""
LEFT JOIN course_sections cs ON c.course_id = cs.course_id
  AND cs.semester_id = (
    SELECT semester_id
    FROM semesters
    WHERE semester_name = {q(v['semester'])}
  )
"""
            group = "GROUP BY c.course_code, c.course_name"
        else:
            select = "SELECT c.course_code, c.course_name, pre.course_name AS prerequisite_name"
            join_open = ""
            group = ""
        return f"""
{select}
FROM prerequisites p
JOIN courses c ON p.course_id = c.course_id
JOIN courses pre ON p.prerequisite_course_id = pre.course_id
{extra_join}
{join_open}
WHERE pre.course_name = {q(v['prereq'])}
  {extra_where}
{group}
{having}
{order}
"""
    dept_join = "JOIN departments d ON c.department_id = d.department_id"
    dept_where = f"AND d.department_name = {q(v['department'])}"
    return make_conversation(conv_id, split, [
        turn(1, f"Những môn nào yêu cầu đã học {v['prereq']} trước khi đăng ký?", sql(), "initial_query", ["self_join"]),
        turn(2, f"Trong số đó, môn nào thuộc khoa {v['department']}?", sql(dept_join, dept_where), "filter_add", ["coreference"]),
        turn(3, f"Cho biết thêm số lớp đang mở ở học kỳ {v['semester']}.", sql(dept_join, dept_where, select_open=True), "aggregate_group_by", ["join_expand", "group_by"]),
        turn(4, f"Chỉ lấy môn có ít nhất {threshold} lớp đang mở.", sql(dept_join, dept_where, select_open=True, having=f"HAVING COUNT(DISTINCT cs.section_id) >= {threshold}"), "having_add", ["having"]),
        turn(5, "Sắp xếp môn có nhiều lớp mở nhất lên trước.", sql(dept_join, dept_where, select_open=True, having=f"HAVING COUNT(DISTINCT cs.section_id) >= {threshold}", order="ORDER BY open_section_count DESC"), "order_add", ["order_by"]),
    ])


def scenario_schedule_change(conv_id, split, rng):
    v = pick_values(rng)
    v["department"] = department_name_for_course(v["course"])
    if v["day2"] == v["day"]:
        v["day2"] = "Thứ 6" if v["day"] != "Thứ 6" else "Thứ 2"

    def sql(day, extra_where="", order="", limit=""):
        return f"""
SELECT c.course_name, cs.section_code, cs.schedule, cs.room,
       cs.capacity - COUNT(e.enrollment_id) AS seats_left
FROM course_sections cs
JOIN courses c ON cs.course_id = c.course_id
JOIN semesters sem ON cs.semester_id = sem.semester_id
JOIN instructors i ON cs.instructor_id = i.instructor_id
JOIN departments d ON i.department_id = d.department_id
LEFT JOIN enrollments e ON cs.section_id = e.section_id AND e.status = 'enrolled'
WHERE c.course_name = {q(v['course'])}
  AND sem.semester_name = {q(v['semester'])}
  AND cs.schedule LIKE {q('%' + day + '%')}
  {extra_where}
GROUP BY c.course_name, cs.section_code, cs.schedule, cs.room, cs.capacity
HAVING COUNT(e.enrollment_id) < cs.capacity
{order}
{limit}
"""
    dept_where = f"AND d.department_name = {q(v['department'])}"
    return make_conversation(conv_id, split, [
        turn(1, f"Tìm lớp môn {v['course']} còn chỗ vào {v['day']} trong học kỳ {v['semester']}.", sql(v["day"]), "initial_query", ["join", "group_by", "having"]),
        turn(2, f"Đổi sang lịch {v['day2']}.", sql(v["day2"]), "filter_replace", ["replace"]),
        turn(3, f"Chỉ lấy lớp do giảng viên khoa {v['department']} phụ trách.", sql(v["day2"], dept_where), "filter_add", ["contextual_filter"]),
        turn(4, "Ưu tiên lớp còn nhiều chỗ hơn.", sql(v["day2"], dept_where, "ORDER BY seats_left DESC"), "order_add", ["order_by"]),
        turn(5, f"Lấy {v['limit']} lớp phù hợp nhất.", sql(v["day2"], dept_where, "ORDER BY seats_left DESC", f"LIMIT {v['limit']}"), "limit_add", ["limit"]),
    ])


def scenario_completed_then_current(conv_id, split, rng):
    v = pick_values(rng)
    threshold = rng.choice([1, 2, 3])
    sql1 = f"""
SELECT DISTINCT s.student_id, s.full_name, m.major_name
FROM students s
JOIN majors m ON s.major_id = m.major_id
JOIN enrollments e ON s.student_id = e.student_id
JOIN course_sections cs ON e.section_id = cs.section_id
JOIN courses c ON cs.course_id = c.course_id
WHERE c.course_name = {q(v['course'])}
  AND e.status = 'completed'
  AND e.grade IN ('A', 'B+', 'B')
"""
    sql2 = f"""
SELECT DISTINCT s.student_id, s.full_name, c2.course_name, cs2.section_code
FROM students s
JOIN enrollments e2 ON s.student_id = e2.student_id
JOIN course_sections cs2 ON e2.section_id = cs2.section_id
JOIN courses c2 ON cs2.course_id = c2.course_id
JOIN semesters sem2 ON cs2.semester_id = sem2.semester_id
WHERE s.student_id IN (
  SELECT e.student_id
  FROM enrollments e
  JOIN course_sections cs ON e.section_id = cs.section_id
  JOIN courses c ON cs.course_id = c.course_id
  WHERE c.course_name = {q(v['course'])}
    AND e.status = 'completed'
    AND e.grade IN ('A', 'B+', 'B')
)
  AND c2.course_name = {q(v['course2'])}
  AND sem2.semester_name = {q(v['semester'])}
  AND e2.status = 'enrolled'
"""
    sql3 = sql2.replace("WHERE s.student_id IN", "JOIN majors m ON s.major_id = m.major_id\nWHERE s.student_id IN") + f" AND m.major_name = {q(v['major'])}"
    sql4 = f"""
SELECT m.major_name, COUNT(DISTINCT s.student_id) AS student_count
FROM students s
JOIN majors m ON s.major_id = m.major_id
JOIN enrollments e2 ON s.student_id = e2.student_id
JOIN course_sections cs2 ON e2.section_id = cs2.section_id
JOIN courses c2 ON cs2.course_id = c2.course_id
JOIN semesters sem2 ON cs2.semester_id = sem2.semester_id
WHERE s.student_id IN (
  SELECT e.student_id
  FROM enrollments e
  JOIN course_sections cs ON e.section_id = cs.section_id
  JOIN courses c ON cs.course_id = c.course_id
  WHERE c.course_name = {q(v['course'])}
    AND e.status = 'completed'
    AND e.grade IN ('A', 'B+', 'B')
)
  AND c2.course_name = {q(v['course2'])}
  AND sem2.semester_name = {q(v['semester'])}
  AND e2.status = 'enrolled'
GROUP BY m.major_name
"""
    sql5 = sql4 + f" HAVING COUNT(DISTINCT s.student_id) >= {threshold}"
    sql6 = sql5 + " ORDER BY student_count DESC"
    return make_conversation(conv_id, split, [
        turn(1, f"Những sinh viên nào đã qua môn {v['course']} với kết quả từ B trở lên?", sql1, "initial_query", ["join"]),
        turn(2, f"Trong nhóm đó, ai đang học môn {v['course2']} ở học kỳ {v['semester']}?", sql2, "join_expand", ["coreference", "subquery"]),
        turn(3, f"Chỉ lấy sinh viên ngành {v['major']}.", sql3, "filter_add", ["contextual_filter"]),
        turn(4, "Đếm lại theo từng ngành thay vì liệt kê từng sinh viên.", sql4, "aggregate_group_by", ["group_by", "aggregate"]),
        turn(5, f"Chỉ giữ ngành có ít nhất {threshold} sinh viên.", sql5, "having_add", ["having"]),
        turn(6, "Sắp xếp ngành có nhiều sinh viên nhất lên trước.", sql6, "order_add", ["order_by"]),
    ])


SCENARIOS = [
    scenario_student_filter,
    scenario_group_by_major,
    scenario_available_sections,
    scenario_waitlist,
    scenario_instructor_workload,
    scenario_prerequisites,
    scenario_schedule_change,
    scenario_completed_then_current,
]


def make_conversation(conv_id, split, turns):
    return {
        "conversation_id": f"{split}_university_conv_{conv_id:06d}",
        "domain": "university_course_registration",
        "db_id": DB_ID,
        "source": "synthetic_stateful_template_v02",
        "source_question": turns[0]["utterance"],
        "source_sql": turns[0]["sql"],
        "turns": turns,
        "final_sql": turns[-1]["sql"],
    }


def generate_conversations():
    rng = random.Random(RANDOM_SEED)
    by_split = {}
    previous_split_sql = set()
    for split, count in SPLIT_COUNTS.items():
        conversations = []
        attempts = 0
        while len(conversations) < count:
            attempts += 1
            if attempts > count * 100:
                raise RuntimeError(f"Could not build non-overlapping source conversations for split {split}")
            idx = len(conversations) + 1
            if previous_split_sql:
                scenario_index = (idx + attempts - 2) % len(SCENARIOS)
            else:
                scenario_index = (idx - 1) % len(SCENARIOS)
            scenario = SCENARIOS[scenario_index]
            conversation = scenario(idx, split, rng)
            conversation_sql = {item["sql"] for item in conversation["turns"]}
            if conversation_sql & previous_split_sql:
                continue
            conversations.append(conversation)
        previous_split_sql.update(
            item["sql"]
            for conversation in conversations
            for item in conversation["turns"]
        )
        by_split[split] = conversations
    return by_split


def build_history(turns, current_index):
    lines = []
    for item in turns[:current_index]:
        lines.append(f"User: {item['utterance']}")
        lines.append(f"SQL: {item['sql']}")
    return "\n".join(lines)


def build_training_samples(conversations, schema_text):
    samples = []
    for conv in conversations:
        turns = conv["turns"]
        for idx, item in enumerate(turns):
            history = build_history(turns, idx)
            if history:
                input_text = (
                    f"Database: {conv['db_id']}\n"
                    f"Schema:\n{schema_text}\n"
                    f"History:\n{history}\n"
                    f"Current question: {item['utterance']}\n"
                    f"Generate SQL:"
                )
            else:
                input_text = (
                    f"Database: {conv['db_id']}\n"
                    f"Schema:\n{schema_text}\n"
                    f"Current question: {item['utterance']}\n"
                    f"Generate SQL:"
                )
            samples.append({
                "id": f"{conv['conversation_id']}_turn_{item['turn_id']}",
                "conversation_id": conv["conversation_id"],
                "turn_id": item["turn_id"],
                "domain": conv["domain"],
                "db_id": conv["db_id"],
                "input": input_text,
                "output": item["sql"],
                "operation": item["operation"],
                "tags": item["tags"],
                "tag_groups": item["tag_groups"],
                "difficulty": item["difficulty"],
                "sql_executable": item["sql_executable"],
                "result_non_empty": item["result_non_empty"],
            })
    return samples


def sql_features(sql):
    upper = " " + sql.upper() + " "
    return {
        "join": " JOIN " in upper,
        "group_by": " GROUP BY " in upper,
        "having": " HAVING " in upper,
        "order_by": " ORDER BY " in upper,
        "limit": " LIMIT " in upper,
        "subquery": bool(re.search(r"\(\s*SELECT\s+", upper)),
        "aggregate": any(fn in upper for fn in ["COUNT(", "AVG(", "SUM(", "MIN(", "MAX("]),
    }


def difficulty_for_sql(sql):
    features = sql_features(sql)
    if features["subquery"]:
        return "hard"
    if (
        features["group_by"]
        or features["having"]
        or features["order_by"]
        or features["limit"]
        or features["aggregate"]
    ):
        return "medium"
    return "easy"


def balance_training_samples(samples, split, excluded_sql):
    buckets = {"easy": [], "medium": [], "hard": []}
    for sample in samples:
        if sample["output"] in excluded_sql:
            continue
        buckets[sample["difficulty"]].append(sample)

    unit_count = min(
        len(buckets["easy"]) // 3,
        len(buckets["medium"]) // 4,
        len(buckets["hard"]) // 3,
    )
    if unit_count == 0:
        return sorted(
            (
                sample
                for samples_by_difficulty in buckets.values()
                for sample in samples_by_difficulty
            ),
            key=lambda item: item["id"],
        )

    rng = random.Random(f"{RANDOM_SEED}:{split}:difficulty_balance")
    balanced = []
    targets = {
        "easy": unit_count * 3,
        "medium": unit_count * 4,
        "hard": unit_count * 3,
    }
    for difficulty, target in targets.items():
        selected = list(buckets[difficulty])
        rng.shuffle(selected)
        balanced.extend(selected[:target])
    balanced.sort(key=lambda item: item["id"])
    return balanced


def count_by(items, key):
    counts = {}
    for item in items:
        value = item[key]
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def sql_overlap_report(sql_by_split):
    split_names = list(sql_by_split)
    pair_counts = {}
    for left_index, left in enumerate(split_names):
        for right in split_names[left_index + 1:]:
            pair_counts[f"{left}-{right}"] = len(sql_by_split[left] & sql_by_split[right])
    return {
        "pair_counts": pair_counts,
        "max_pair_overlap": max(pair_counts.values()) if pair_counts else 0,
    }


def validate_conversations(conversations):
    conn = sqlite3.connect(DB_PATH)
    failures = []
    empty_results = 0
    for conv in conversations:
        if conv["final_sql"] != conv["turns"][-1]["sql"]:
            failures.append((conv["conversation_id"], "final_sql mismatch"))
        for expected_id, item in enumerate(conv["turns"], start=1):
            if item["turn_id"] != expected_id:
                failures.append((conv["conversation_id"], f"bad turn_id {item['turn_id']}"))
            try:
                rows = conn.execute(f"SELECT 1 FROM ({item['sql']}) AS generated_query LIMIT 1").fetchmany(1)
                item["sql_executable"] = True
                item["difficulty"] = difficulty_for_sql(item["sql"])
                item["result_non_empty"] = bool(rows)
                if not rows:
                    empty_results += 1
            except Exception as exc:
                item["sql_executable"] = False
                item["difficulty"] = difficulty_for_sql(item["sql"])
                item["result_non_empty"] = False
                failures.append((conv["conversation_id"], item["turn_id"], str(exc), item["sql"]))
    conn.close()
    if failures:
        sample = json.dumps(failures[:5], ensure_ascii=False, indent=2)
        raise RuntimeError(f"SQL validation failed:\n{sample}")
    return empty_results


def summarize(by_split, empty_results, training_by_split):
    operation_counts = {}
    tag_counts = {}
    tag_group_counts = {}
    feature_counts = {}
    split_stats = {}
    total_conversations = 0
    total_turns = 0

    for split, conversations in by_split.items():
        turns = [item for conv in conversations for item in conv["turns"]]
        total_conversations += len(conversations)
        total_turns += len(turns)
        split_stats[split] = {
            "conversations": len(conversations),
            "turns": len(turns),
            "avg_turns": round(len(turns) / len(conversations), 2),
            "min_turns": min(len(conv["turns"]) for conv in conversations),
            "max_turns": max(len(conv["turns"]) for conv in conversations),
            "turn_difficulty_counts": count_by(turns, "difficulty"),
            "balanced_training_samples": len(training_by_split[split]),
            "balanced_training_difficulty_counts": count_by(training_by_split[split], "difficulty"),
        }
        for item in turns:
            operation_counts[item["operation"]] = operation_counts.get(item["operation"], 0) + 1
            for tag in item["tags"]:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            for group, tags in item["tag_groups"].items():
                tag_group_counts[group] = tag_group_counts.get(group, 0) + len(tags)
            for feature, present in sql_features(item["sql"]).items():
                if present:
                    feature_counts[feature] = feature_counts.get(feature, 0) + 1

    return {
        "dataset": "university_multi_turn_v02",
        "db_id": DB_ID,
        "total_conversations": total_conversations,
        "total_turns": total_turns,
        "empty_result_queries": empty_results,
        "splits": split_stats,
        "operation_counts": dict(sorted(operation_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "tag_group_counts": dict(sorted(tag_group_counts.items())),
        "sql_feature_counts": dict(sorted(feature_counts.items())),
        "source_conversation_exact_sql_overlap": sql_overlap_report({
            split: {item["sql"] for conv in conversations for item in conv["turns"]}
            for split, conversations in by_split.items()
        }),
        "accuracy_split_exact_sql_overlap": sql_overlap_report({
            split: {item["output"] for item in samples}
            for split, samples in training_by_split.items()
        }),
    }


def write_outputs(by_split, seed_sql):
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    schema_text = schema_prompt()
    (SCHEMA_DIR / "schema.sql").write_text(build_schema_sql() + "\n", encoding="utf-8")
    (SCHEMA_DIR / "seed_data.sql").write_text(seed_sql + "\n", encoding="utf-8")
    save_json(build_schema_metadata(), SCHEMA_DIR / "schema.json")
    save_json(build_tables_json(), OUT_DIR / "tables.json")

    training_by_split = {}
    used_training_sql = set()
    for split, conversations in by_split.items():
        for conv in conversations:
            for item in conv["turns"]:
                item["used_for_accuracy"] = False
        samples = build_training_samples(conversations, schema_text)
        samples = balance_training_samples(samples, split, set())
        for sample in samples:
            sample["used_for_accuracy"] = True
        used_training_sql.update(item["output"] for item in samples)
        selected_ids = {item["id"] for item in samples}
        for conv in conversations:
            for item in conv["turns"]:
                item["used_for_accuracy"] = f"{conv['conversation_id']}_turn_{item['turn_id']}" in selected_ids
        save_json(conversations, CONV_DIR / f"university_multi_turn_{split}_v02.json")
        training_by_split[split] = samples
        save_json(samples, TRAINING_DIR / f"university_train_format_{split}_v02.json")
    return training_by_split


def main():
    seed_sql = create_database()
    by_split = generate_conversations()
    all_conversations = [conv for conversations in by_split.values() for conv in conversations]
    empty_results = validate_conversations(all_conversations)
    training_by_split = write_outputs(by_split, seed_sql)
    report = summarize(by_split, empty_results, training_by_split)
    save_json(report, OUT_DIR / "report_v02.json")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
