export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.name = new.target.name;
    this.status = status;
  }
}
export class UnauthorizedError extends ApiError {}
export class ForbiddenError extends ApiError {}
export class ValidationError extends ApiError {
  messages: string[];
  constructor(messages: string[], status = 422) {
    super(messages.join(' ') || 'The request was not accepted.', status);
    this.messages = messages;
  }
}
export class ServerError extends ApiError {}
export class NetworkError extends ApiError {}
export class ResponseShapeError extends ApiError {}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return 'Something went wrong. Please try again.';
}

