'use client';

import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

function LoginForm() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    const res = await fetch('/api/dashboard/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });

    if (res.ok) {
      const redirect = searchParams.get('redirect') || '/dashboard';
      router.push(redirect);
    } else {
      setError('Invalid password');
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Enter password"
        className="w-full px-4 py-2 border border-gray-300 rounded-lg mb-4 focus:outline-none focus:ring-2 focus:ring-sky-500"
        autoFocus
      />
      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}
      <button
        type="submit"
        disabled={loading}
        className="w-full px-4 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700 disabled:opacity-50 transition-colors"
      >
        {loading ? 'Logging in...' : 'Login'}
      </button>
    </form>
  );
}

export default function DashboardLogin() {
  return (
    <div className="max-w-sm mx-auto px-6 py-24">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Dashboard Login</h1>
      <Suspense fallback={<div>Loading...</div>}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
