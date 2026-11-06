import { z } from 'zod';

export const SubjectSchema = z.object({
  id: z.number(),
  code: z.string(),
  name: z.string(),
  is_lab: z.boolean().default(false),
});

export const FacultyRefSchema = z.object({
  id: z.number().optional(),
  code: z.string(),
  name: z.string(),
});

export const SlotSchema = z.object({
  id: z.number(),
  day_of_week: z.number(),
  day_name: z.string(),
  start_time: z.string(),
  end_time: z.string(),
  room: z.string().nullable().optional(),
  section: z.string().nullable().optional(),
  batch: z.string().nullable().optional(),
  needs_review: z.boolean(),
  subject: SubjectSchema,
  faculty: z.array(FacultyRefSchema),
});
export const SlotListSchema = z.array(SlotSchema);
export const NextClassSchema = SlotSchema.nullable();

export const ChatReplySchema = z.object({
  reply: z.string(),
  tools_used: z.array(z.object({ name: z.string(), args: z.record(z.string(), z.unknown()) })),
  fallback: z.boolean(),
  elapsed_ms: z.number(),
  assistant_time: z.string(),
});

export const ReviewItemSchema = z.object({
  id: z.number(),
  branch_code: z.string().nullable(),
  semester: z.number().nullable(),
  day_name: z.string(),
  start_time: z.string().nullable(),
  end_time: z.string().nullable(),
  batch: z.string().nullable().optional(),
  room: z.string().nullable().optional(),
  needs_review: z.boolean(),
  subject: z.object({ code: z.string(), name: z.string() }).nullable(),
  faculty: z.array(z.object({ code: z.string(), name: z.string() })),
  raw_cell_text: z.string().nullable().optional(),
});
export const ReviewQueueSchema = z.object({
  total: z.number(),
  items: z.array(ReviewItemSchema),
});
export const FacultyListSchema = z.array(z.object({ code: z.string(), name: z.string() }));

export const EventSchema = z.object({
  id: z.number(),
  event_type: z.string(),
  title: z.string(),
  start_date: z.string(),
  end_date: z.string(),
  description: z.string().nullable().optional(),
  suppresses_timetable: z.boolean(),
});
export const EventListSchema = z.array(EventSchema);

export const UserSchema = z.object({
  id: z.number().optional(),
  email: z.string(),
  role: z.enum(['student', 'faculty', 'admin']),
  branch_code: z.string().nullable().optional(),
  semester: z.number().nullable().optional(),
  section: z.string().nullable().optional(),
  batch: z.string().nullable().optional(),
  roll_no: z.string().nullable().optional(),
});

export const TokenPairSchema = z.object({ access_token: z.string(), refresh_token: z.string() });
export const AccessTokenSchema = z.object({ access_token: z.string() });
export const SuppressedSchema = z.object({
  suppressed: z.boolean(),
  check_date: z.string(),
});

export type Slot = z.infer<typeof SlotSchema>;
export type ChatReply = z.infer<typeof ChatReplySchema>;
export type ReviewItem = z.infer<typeof ReviewItemSchema>;
export type ReviewQueue = z.infer<typeof ReviewQueueSchema>;
export type AcademicEvent = z.infer<typeof EventSchema>;
export type User = z.infer<typeof UserSchema>;
export type Suppressed = z.infer<typeof SuppressedSchema>;

