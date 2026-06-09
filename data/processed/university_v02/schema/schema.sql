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
