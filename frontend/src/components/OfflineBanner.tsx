import { WifiOff } from 'lucide-react';
import { useOnline } from '../hooks/useOnline';

export function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return (
    <div role="alert" className="flex items-center justify-center gap-2 bg-amber-100 px-3 py-2 text-sm font-medium text-amber-900">
      <WifiOff className="h-4 w-4" aria-hidden="true" />
      You are offline. Showing saved data; new requests will fail until you reconnect.
    </div>
  );
}
