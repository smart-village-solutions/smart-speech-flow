import { useEffect, useState } from 'react';
import WebSocketService from '../services/WebSocketService';
import type { ConnectionStatus } from '../services/WebSocketService';

export default function ConnectionStatusIndicator() {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');

  useEffect(() => {
    const unsubscribe = WebSocketService.onStatusChange(setStatus);
    return unsubscribe;
  }, []);

  const statusConfig = {
    connected: {
      color: 'bg-green-500',
      label: 'Verbunden',
      pulse: false,
    },
    connecting: {
      color: 'bg-yellow-500',
      label: 'Verbinde...',
      pulse: true,
    },
    disconnected: {
      color: 'bg-gray-400',
      label: 'Getrennt',
      pulse: false,
    },
    error: {
      color: 'bg-red-500',
      label: 'Fehler',
      pulse: false,
    },
  };

  const config = statusConfig[status];

  return (
    <div className="flex items-center space-x-2 text-sm">
      <div className="relative">
        <div className={`w-3 h-3 rounded-full ${config.color}`} />
        {config.pulse && (
          <div className={`absolute inset-0 w-3 h-3 rounded-full ${config.color} animate-ping`} />
        )}
      </div>
      <span className="text-gray-600">{config.label}</span>
    </div>
  );
}
