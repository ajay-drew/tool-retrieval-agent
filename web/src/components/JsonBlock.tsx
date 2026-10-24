interface Props {
  label: string;
  value: unknown;
  open?: boolean;
}

export function JsonBlock({ label, value, open = false }: Props) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <details className="json" open={open}>
      <summary>{label}</summary>
      <pre>{text}</pre>
    </details>
  );
}
