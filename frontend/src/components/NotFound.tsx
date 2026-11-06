export function NotFound() {
  return (
    <main className="mx-auto mt-24 max-w-md px-4 text-center">
      <p className="text-5xl font-extrabold text-blue-600">404</p>
      <h1 className="mt-2 text-xl font-bold text-slate-900 dark:text-white">Page not found</h1>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
        That address does not exist in the MITS Campus app.
      </p>
      <a href="/" className="mt-4 inline-block rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">
        Go to the app
      </a>
    </main>
  );
}

