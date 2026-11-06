import { QueryClient } from '@tanstack/react-query';
import { ForbiddenError, UnauthorizedError, ValidationError } from './services/errors';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: true,
        retry: (failureCount, error) => {
          if (
            error instanceof UnauthorizedError ||
            error instanceof ForbiddenError ||
            error instanceof ValidationError
          ) {
            return false;
          }
          return failureCount < 1;
        },
      },
    },
  });
}

