export function Footer() {
  return (
    <footer className="border-t border-gray-100 mt-auto">
      <div className="max-w-2xl mx-auto px-6 py-8 text-center text-gray-400 text-sm">
        <p>&copy; {new Date().getFullYear()} Blog. All rights reserved.</p>
      </div>
    </footer>
  );
}
