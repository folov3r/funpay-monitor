import { useEffect, type ReactNode } from "react";

interface ModalProps {
  caption: string;
  title: string;
  onClose: () => void;
  children: ReactNode;
  width?: number;
  className?: string;
}

export function Modal({ caption, title, onClose, children, width = 560, className }: ModalProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className={className ? `modal ${className}` : "modal"} style={{ width }} role="dialog" aria-modal="true">
        <div className="modal-caption">{caption}</div>
        <h2 className="modal-title">{title}</h2>
        <button className="modal-close" type="button" onClick={onClose} aria-label="Закрыть">
          ✕
        </button>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function ConfirmDialog({
  title,
  lines,
  confirm,
  cancel = "Отмена",
  onConfirm,
  onCancel,
}: {
  title: string;
  lines: string[];
  confirm: string;
  cancel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal caption="ПОДТВЕРЖДЕНИЕ" title={title} onClose={onCancel} width={440}>
      <div className="confirm-lines">
        {lines.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
      <div className="modal-actions end">
        <button type="button" className="btn ghost" onClick={onCancel}>
          {cancel}
        </button>
        <button type="button" className="btn danger" onClick={onConfirm}>
          {confirm}
        </button>
      </div>
    </Modal>
  );
}
