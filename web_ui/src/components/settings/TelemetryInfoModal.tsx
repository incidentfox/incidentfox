'use client';

import { X, Check, ShieldCheck, Activity, Users, Gauge } from 'lucide-react';

interface TelemetryInfoModalProps {
  onClose: () => void;
}

export function TelemetryInfoModal({ onClose }: TelemetryInfoModalProps) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl w-full max-w-md shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="relative bg-gradient-to-br from-blue-500 via-blue-600 to-indigo-600 px-6 py-6 text-white">
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-white/80 hover:text-white transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>

          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/20 flex items-center justify-center backdrop-blur-sm">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold">Telemetry</h1>
              <p className="text-white/80 text-sm">Anonymous usage metrics</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-5 max-h-[60vh] overflow-y-auto">
          {/* What we collect */}
          <div>
            <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-500" />
              What we collect
            </h2>
            <div className="grid grid-cols-2 gap-2">
              <CollectItem icon={<Gauge className="w-3.5 h-3.5" />} text="Run counts & success rates" />
              <CollectItem icon={<Activity className="w-3.5 h-3.5" />} text="Performance metrics" />
              <CollectItem icon={<Users className="w-3.5 h-3.5" />} text="Active team counts" />
              <CollectItem icon={<ShieldCheck className="w-3.5 h-3.5" />} text="Error types" />
            </div>
          </div>

          {/* What we don't collect */}
          <div>
            <h2 className="text-sm font-medium text-gray-900 dark:text-white mb-3 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-green-500" />
              Never collected
            </h2>
            <div className="flex flex-wrap gap-2">
              <NeverItem text="Prompts or messages" />
              <NeverItem text="API keys" />
              <NeverItem text="Personal info" />
              <NeverItem text="Knowledge base content" />
              <NeverItem text="IP addresses" />
            </div>
          </div>

          {/* How it helps */}
          <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Telemetry helps us improve IncidentFox by understanding usage patterns and identifying performance issues.
              Data is aggregated, anonymized, and never shared with third parties.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-gray-50 dark:bg-gray-800/50 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-900 dark:bg-white dark:text-gray-900 text-white rounded-lg font-medium text-sm hover:bg-gray-800 dark:hover:bg-gray-100 transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}

function CollectItem({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg px-2.5 py-2">
      <span className="text-blue-500">{icon}</span>
      {text}
    </div>
  );
}

function NeverItem({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400 rounded-full px-2.5 py-1">
      <Check className="w-3 h-3" />
      {text}
    </div>
  );
}
