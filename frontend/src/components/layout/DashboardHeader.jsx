export default function DashboardHeader() {
  return (
    <header className="flex flex-col gap-4 border-b bg-white px-6 py-5 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Company Prospecting
        </h1>

        <p className="mt-1 text-sm text-muted-foreground">
          Review companies and track their sales stages.
        </p>
      </div>
    </header>
  );
}
