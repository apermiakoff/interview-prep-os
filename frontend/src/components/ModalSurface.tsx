import { type ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

interface Props {
  children: ReactNode;
  className: string;
  label: string;
  modal: boolean;
  onClose: () => void;
  closeDisabled?: boolean;
  closeOnBackdrop?: boolean;
}

/** A portal-backed modal on narrow screens and a non-modal dock when requested. */
export function ModalSurface({ children, className, label, modal, onClose, closeDisabled = false, closeOnBackdrop = false }: Props) {
  const surface = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const disabledRef = useRef(closeDisabled);
  closeRef.current = onClose;
  disabledRef.current = closeDisabled;

  useEffect(() => {
    const node = surface.current;
    if (!node) return;
    const focusable = () => Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
      .filter(item => item.getAttribute("aria-hidden") !== "true");
    if (modal) focusable()[0]?.focus();

    const background = document.querySelector<HTMLElement>(".app-shell");
    const previousInert = background?.inert ?? false;
    const previousOverflow = document.body.style.overflow;
    const previousPaddingRight = document.body.style.paddingRight;
    if (modal) {
      if (background) background.inert = true;
      const scrollbar = window.innerWidth - document.documentElement.clientWidth;
      document.body.style.overflow = "hidden";
      if (scrollbar > 0) document.body.style.paddingRight = `${scrollbar}px`;
    }

    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !disabledRef.current) {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (!modal || event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) {
        event.preventDefault();
        node.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const activeInside = document.activeElement instanceof Node && node.contains(document.activeElement);
      if (!activeInside) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keydown, true);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      if (modal) {
        if (background) background.inert = previousInert;
        document.body.style.overflow = previousOverflow;
        document.body.style.paddingRight = previousPaddingRight;
      }
    };
  }, [modal]);

  const content = (
    <div
      ref={surface}
      className={className}
      role={modal ? "dialog" : "complementary"}
      aria-modal={modal ? "true" : undefined}
      aria-label={label}
      tabIndex={-1}
      onClick={event => {
        if (closeOnBackdrop && event.target === event.currentTarget && !closeDisabled) onClose();
      }}
    >
      {children}
    </div>
  );
  return modal ? createPortal(content, document.body) : content;
}
