export const student = {
  id: 1,
  email: 'stu@mits.ac.in',
  role: 'student',
  branch_code: 'AI',
  semester: 3,
  section: null,
  batch: 'A',
  roll_no: '0101AI',
};
export const admin = { ...student, id: 2, email: 'admin@mits.ac.in', role: 'admin', branch_code: null, semester: null };

export function slot(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    day_of_week: 0,
    day_name: 'Monday',
    start_time: '09:00:00',
    end_time: '10:00:00',
    room: 'LT-101',
    section: null,
    batch: null,
    needs_review: false,
    subject: { id: 1, code: 'AI-301', name: 'Data Structures', is_lab: false },
    faculty: [{ id: 1, code: 'SO', name: 'Dr. Satyam Omar' }],
    ...over,
  };
}

export function chatReply(over: Record<string, unknown> = {}) {
  return { reply: 'You have Data Structures at 9:00 AM.', tools_used: [], fallback: false, elapsed_ms: 1200, assistant_time: 'Monday 08:30 AM', ...over };
}

export const reviewItem = {
  id: 7,
  branch_code: 'AI',
  semester: 3,
  day_name: 'Tuesday',
  start_time: '10:00',
  end_time: '11:00',
  batch: 'A',
  room: 'LAB-2',
  needs_review: true,
  subject: { code: 'AI-307', name: 'Python Lab' },
  faculty: [{ code: 'SO', name: 'Dr. Satyam Omar' }],
  raw_cell_text: 'AI-307 SO?',
};

