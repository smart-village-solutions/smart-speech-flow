import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';

const CORRECT_PASSWORD = 'ssf2025kassel';

export default function LandingPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => sessionStorage.getItem('authenticated') === 'true'
  );

  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (password === CORRECT_PASSWORD) {
      sessionStorage.setItem('authenticated', 'true');
      setIsAuthenticated(true);
      setError('');
    } else {
      setError('Ungültiges Passwort');
    }
  };

  if (isAuthenticated) {
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <Header />
        <div className="flex-1 flex items-center justify-center px-4 py-12 sm:py-20">
          <div className="bg-white rounded-card-lg shadow-card p-8 sm:p-12 w-full max-w-md">
            <h1 className="text-4xl sm:text-5xl font-bold text-center text-text mb-8 sm:mb-12 leading-tight">
              Smart Speech Flow
            </h1>
            <div className="grid grid-cols-1 gap-6">
              <Link
                to="/admin"
                className="block w-full bg-primary hover:brightness-90 text-white font-semibold py-4 px-8 rounded-card transition duration-200 shadow-md text-center text-lg"
              >
                Intern (Verwaltung)
              </Link>
              <Link
                to="/customer"
                className="block w-full bg-primary hover:brightness-90 text-white font-semibold py-4 px-8 rounded-card transition duration-200 shadow-md text-center text-lg"
              >
                Kunde
              </Link>
            </div>
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <div className="flex-1 flex items-center justify-center px-4 py-12 sm:py-20">
        <div className="bg-white rounded-card-lg shadow-card p-8 sm:p-12 w-full max-w-md">
          <h1 className="text-4xl sm:text-5xl font-bold text-center text-text mb-4 leading-tight">
            Smart Speech Flow
          </h1>
          <p className="text-center text-gray-600 mb-8 sm:mb-10 text-base sm:text-lg leading-relaxed">
            Bitte geben Sie das Passwort ein
          </p>
          <form onSubmit={handlePasswordSubmit} className="grid grid-cols-1 gap-6">
            <div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Passwort"
                className="w-full px-6 py-4 border border-gray-300 rounded-card focus:ring-2 focus:ring-primary focus:border-transparent outline-none text-base"
              />
            </div>
            {error && (
              <p className="text-red-600 text-base text-center">{error}</p>
            )}
            <button
              type="submit"
              className="w-full bg-primary hover:brightness-90 text-white font-semibold py-4 px-8 rounded-card transition duration-200 shadow-md text-lg"
            >
              Anmelden
            </button>
          </form>
        </div>
      </div>
      <Footer />
    </div>
  );
}
