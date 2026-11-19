import type { ReactNode } from "react";

interface Props {
  title: string;
  subtitle: string;
  action?: ReactNode;
  tools?: ReactNode;
}

export function PageHeader({ title, subtitle, action, tools }: Props) {
  return (
    <header className="page-header">
      <div className="crumbs">Мониторинг · {title}</div>
      <div className="head-row">
        <div className="head-text">
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        {tools || action ? (
          <div className="head-tools">
            {tools}
            {action}
          </div>
        ) : null}
      </div>
      <div className="page-divider" />
    </header>
  );
}
