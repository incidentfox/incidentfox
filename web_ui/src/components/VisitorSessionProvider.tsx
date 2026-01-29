'use client';

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react';
import { useIdentity } from '@/lib/useIdentity';

interface VisitorSessionStatus {
  status: 'active' | 'warned' | 'expired';
  warning_seconds_remaining?: number;
}

interface VisitorSessionContextType {
  isVisitor: boolean;
  sessionStatus: VisitorSessionStatus | null;
  endSession: () => Promise<void>;
}

const VisitorSessionContext = createContext<VisitorSessionContextType>({
  isVisitor: false,
  sessionStatus: null,
  endSession: async () => {},
});

export function useVisitorSession() {
  return useContext(VisitorSessionContext);
}

interface VisitorSessionProviderProps {
  children: ReactNode;
}

export function VisitorSessionProvider({ children }: VisitorSessionProviderProps) {
  const { identity } = useIdentity();
  const [sessionStatus, setSessionStatus] = useState<VisitorSessionStatus | null>(null);

  const isVisitor = identity?.auth_kind === 'visitor';

  // Heartbeat polling for visitor sessions
  useEffect(() => {
    if (!isVisitor) {
      setSessionStatus(null);
      return;
    }

    // Send heartbeat and check status
    const sendHeartbeat = async () => {
      try {
        const res = await fetch('/api/visitor/heartbeat', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
        });
        const data = await res.json();

        setSessionStatus({
          status: data.status,
          warning_seconds_remaining: data.warning_seconds_remaining,
        });

        // If session expired, reload to trigger re-login
        if (data.status === 'expired') {
          // Clear cookies and redirect to login
          await fetch('/api/visitor/end-session', { method: 'POST' });
          window.location.reload();
        }
      } catch (e) {
        console.error('Failed to send visitor heartbeat:', e);
      }
    };

    // Initial heartbeat
    sendHeartbeat();

    // Poll every 30 seconds
    const interval = setInterval(sendHeartbeat, 30000);

    return () => clearInterval(interval);
  }, [isVisitor]);

  const endSession = useCallback(async () => {
    await fetch('/api/visitor/end-session', { method: 'POST' });
    window.location.reload();
  }, []);

  return (
    <VisitorSessionContext.Provider value={{ isVisitor, sessionStatus, endSession }}>
      {children}
    </VisitorSessionContext.Provider>
  );
}
