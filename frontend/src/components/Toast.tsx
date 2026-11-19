import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ToastTone = "accent" | "mint" | "amber" | "red";

export interface ToastMessage {
  title: string;
  subtitle?: string;
  tone?: ToastTone;
}

const ToastContext = createContext<(message: ToastMessage) => void>(() => undefined);

const TOAST_LIFETIME = 2600;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<(ToastMessage & { id: number }) | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const show = useCallback((next: ToastMessage) => {
    window.clearTimeout(timer.current);
    setMessage({ ...next, id: Date.now() });
    timer.current = window.setTimeout(() => setMessage(null), TOAST_LIFETIME);
  }, []);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      {message ? (
        <div className={`toast tone-${message.tone ?? "accent"}`} key={message.id} role="status">
          <div className="toast-bar" />
          <div className="toast-copy">
            <strong>{message.title}</strong>
            {message.subtitle ? <span>{message.subtitle}</span> : null}
          </div>
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
