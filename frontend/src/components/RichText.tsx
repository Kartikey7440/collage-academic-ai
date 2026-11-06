import type { ReactNode } from 'react';

/** Safe mini-formatter: line breaks, **bold** and "* " bullets. Everything is rendered as React text. */
function inline(text: string): ReactNode[] {
  return text.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 === 1 ? <strong key={i}>{part}</strong> : part));
}

export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (key: string) => {
    if (bullets.length === 0) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={`ul${key}`} className="my-1 list-disc space-y-0.5 pl-5">
        {items.map((b, i) => (
          <li key={i}>{inline(b)}</li>
        ))}
      </ul>,
    );
  };
  text.split('\n').forEach((line, i) => {
    const bullet = /^\s*\* (.*)$/.exec(line);
    if (bullet) {
      bullets.push(bullet[1]);
      return;
    }
    flush(String(i));
    if (line.trim() === '') blocks.push(<div key={`s${i}`} className="h-2" />);
    else blocks.push(<p key={`p${i}`}>{inline(line)}</p>);
  });
  flush('end');
  return <div className="space-y-0.5 break-words">{blocks}</div>;
}

