import { AppProviders } from '@/app/providers/AppProviders';
import { AppRoutes } from '@/app/router/AppRoutes';
import './index.css';

export default function App() {
  return (
    <AppProviders>
      <AppRoutes />
    </AppProviders>
  );
}
