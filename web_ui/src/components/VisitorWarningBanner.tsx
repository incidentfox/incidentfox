'use client';

import { useEffect, useState } from 'react';
import { Clock, Users, LogOut } from 'lucide-react';
import { useVisitorSession } from './VisitorSessionProvider';

export function VisitorWarningBanner() {
  const { isVisitor, sessionStatus, endSession } = useVisitorSession();
  const [countdown, setCountdown] = useState<number | null>(null);

  // Update countdown every second when warned
  useEffect(() => {
    if (sessionStatus?.status !== 'warned' || !sessionStatus.warning_seconds_remaining) {
      setCountdown(null);
      return;
    }

    setCountdown(sessionStatus.warning_seconds_remaining);

    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev === null || prev <= 0) return 0;
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [sessionStatus?.status, sessionStatus?.warning_seconds_remaining]);

  if (!isVisitor || sessionStatus?.status !== 'warned') {
    return null;
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm">
      <div className="bg-orange-600 text-white rounded-lg shadow-lg p-4 animate-pulse">
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0">
            <Users className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h4 className="font-semibold text-sm">Another user is waiting</h4>
            <p className="text-xs text-orange-100 mt-1">
              Your session will end in{' '}
              <span className="font-bold text-white">
                {countdown !== null ? formatTime(countdown) : '...'}
              </span>
            </p>
            <div className="flex items-center gap-2 mt-3">
              <button
                onClick={endSession}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium bg-white text-orange-600 rounded hover:bg-orange-50 transition-colors"
              >
                <LogOut className="w-3 h-3" />
                Leave now
              </button>
              <a
                href="mailto:support@incidentfox.ai?subject=IncidentFox Demo Interest"
                className="text-xs text-orange-100 hover:text-white underline"
              >
                Contact us for a team account
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
