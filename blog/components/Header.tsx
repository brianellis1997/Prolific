import Link from 'next/link';

export function Header() {
  return (
    <header className="border-b border-gray-100">
      <div className="max-w-2xl mx-auto px-6 py-6 flex items-center justify-between">
        <Link href="/" className="text-xl font-semibold text-gray-900 hover:text-sky-600 transition-colors">
          Blog
        </Link>
        <nav className="flex gap-6">
          <Link href="/" className="text-gray-600 hover:text-gray-900 transition-colors">
            Posts
          </Link>
          <Link href="/about" className="text-gray-600 hover:text-gray-900 transition-colors">
            About
          </Link>
        </nav>
      </div>
    </header>
  );
}
