export default function Header({ title }: { title: string }) {
  return (
    <header className="bg-white border-b border-gray-200 px-8 py-4">
      <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
    </header>
  );
}
