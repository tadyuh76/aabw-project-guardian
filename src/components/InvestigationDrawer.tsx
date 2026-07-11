import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  CalendarBlank,
  CheckCircle,
  ClipboardText,
  Package,
  ShieldCheck,
  X,
} from "@phosphor-icons/react";
import {
  PRODUCTS,
  SOURCE_LABELS,
  formatPercent,
  type ProductId,
  type deriveDashboard,
} from "../data/dashboard";

export type CreatedAction = {
  id: string;
  signalId: string;
  productIds: ProductId[];
  scopeLabel: string;
  owner: string;
  dueDate: string;
  status: "Open";
  createdAt: string;
};

type DashboardData = ReturnType<typeof deriveDashboard>;

type InvestigationDrawerProps = {
  data: DashboardData;
  onClose: () => void;
  onCreateAction: (action: CreatedAction) => void;
};

export function InvestigationDrawer({ data, onClose, onCreateAction }: InvestigationDrawerProps) {
  const [owner, setOwner] = useState("E-commerce Operations");
  const [dueDate, setDueDate] = useState("2026-07-13");
  const [created, setCreated] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previousActiveElement.current = document.activeElement as HTMLElement | null;
    const backgroundElements = document.querySelectorAll<HTMLElement>(
      ".sidebar, .topbar, .dashboard",
    );
    backgroundElements.forEach((element) => element.setAttribute("inert", ""));

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !drawerRef.current) return;

      const focusable = [...drawerRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      )].filter((element) => element.getAttribute("aria-hidden") !== "true");
      if (!focusable.length) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    document.body.classList.add("drawer-open");
    requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("drawer-open");
      backgroundElements.forEach((element) => element.removeAttribute("inert"));
      previousActiveElement.current?.focus();
    };
  }, [onClose]);

  const createAction = () => {
    onCreateAction({
      id: `ACT-${Date.now()}`,
      signalId: "SIG-PACKAGING-72H",
      productIds: data.selectedProducts.map((product) => product.id),
      scopeLabel: data.scopeLabel,
      owner,
      dueDate,
      status: "Open",
      createdAt: "11 Jul 2026, 09:15",
    });
    setCreated(true);
  };

  const topHypothesis = data.hypotheses[0];
  const supportingEvidence = data.evidence.filter((item) => item.stance === "support");
  const contradictingEvidence = data.evidence.filter((item) => item.stance === "contradict");

  return (
    <div className="drawer-layer" role="presentation" onMouseDown={onClose}>
      <aside
        className="investigation-drawer"
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="investigation-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <span className="eyebrow">Investigation</span>
            <h2 id="investigation-title">Packaging complaint signal</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onClose}
            ref={closeButtonRef}
          >
            <X size={19} aria-label="Close investigation" />
          </button>
        </header>

        <div className="drawer-body">
          <section className="drawer-section drawer-summary">
            <div className="drawer-summary__icon">
              <ShieldCheck size={23} weight="fill" aria-hidden="true" />
            </div>
            <div>
              <span className={`status-pill status-pill--${data.status ?? "watch"}`}>
                {data.status ?? "No cohort"}
              </span>
              <h3>{data.headline}</h3>
              <p>
                {data.currentComplaints} matching complaints from {data.currentReviews} canonical reviews.
              </p>
            </div>
          </section>

          <section className="drawer-section">
            <div className="section-heading section-heading--compact">
              <div>
                <span className="eyebrow">Products in scope</span>
                <h3>{data.selectedProducts.length} selected</h3>
              </div>
            </div>
            <div className="scope-products">
              {data.selectedProducts.map((product) => (
                <div className="scope-product" key={product.id}>
                  <Package size={18} aria-hidden="true" />
                  <span>
                    <strong>{product.name}</strong>
                    <small>{product.sku} · {product.current.complaints}/{product.current.reviews} complaints</small>
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section className="drawer-section">
            <div className="section-heading section-heading--compact">
              <div>
                <span className="eyebrow">Root-cause hypothesis</span>
                <h3>{topHypothesis?.title ?? "Not enough evidence"}</h3>
              </div>
              {topHypothesis && (
                <span className="confidence-badge">
                  {Math.round(topHypothesis.confidence * 100)}% confidence
                </span>
              )}
            </div>
            {topHypothesis ? (
              <>
                <p className="drawer-copy">{topHypothesis.summary}</p>
                <div className="hypothesis-balance">
                  <span><strong>{topHypothesis.support}</strong> supporting</span>
                  <span><strong>{topHypothesis.contradict}</strong> contradicting</span>
                </div>
              </>
            ) : (
              <p className="drawer-copy">Select a larger product cohort to generate a defensible hypothesis.</p>
            )}
          </section>

          <section className="drawer-section">
            <div className="section-heading section-heading--compact">
              <div>
                <span className="eyebrow">Supporting evidence</span>
                <h3>{supportingEvidence.length} representative samples</h3>
              </div>
            </div>
            <p className="drawer-copy drawer-copy--evidence">
              Representative excerpts from {data.currentComplaints} matching complaints in this cohort.
            </p>
            <div className="drawer-evidence-list">
              {supportingEvidence.slice(0, 4).map((item) => {
                const product = PRODUCTS.find((candidate) => candidate.id === item.productId);
                return (
                  <article className="drawer-evidence" key={item.id}>
                    <p>“{item.quote}”</p>
                    <footer>
                      <span>{product?.shortName}</span>
                      <span>{SOURCE_LABELS[item.source]}</span>
                    </footer>
                  </article>
                );
              })}
            </div>
            {contradictingEvidence.length > 0 && (
              <div className="contradicting-evidence">
                <span className="eyebrow">Contradicting evidence</span>
                {contradictingEvidence.slice(0, 2).map((item) => {
                  const product = PRODUCTS.find((candidate) => candidate.id === item.productId);
                  return (
                    <article className="drawer-evidence" key={item.id}>
                      <p>“{item.quote}”</p>
                      <footer>
                        <span>{product?.shortName}</span>
                        <span>{SOURCE_LABELS[item.source]}</span>
                      </footer>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="drawer-section action-form">
            <div className="section-heading section-heading--compact">
              <div>
                <span className="eyebrow">Recommended action</span>
                <h3>Audit seal and protective-wrap process</h3>
              </div>
              <ClipboardText size={20} aria-hidden="true" />
            </div>
            <p className="drawer-copy">
              Review the packaging batch for the selected products and monitor complaint share for 48 hours.
            </p>
            <div className="form-row">
              <label>
                Owner
                <select value={owner} onChange={(event) => setOwner(event.target.value)}>
                  <option>E-commerce Operations</option>
                  <option>Quality Assurance</option>
                  <option>Customer Experience</option>
                </select>
              </label>
              <label>
                Due date
                <span className="input-with-icon">
                  <CalendarBlank size={16} aria-hidden="true" />
                  <input
                    type="date"
                    value={dueDate}
                    onChange={(event) => setDueDate(event.target.value)}
                  />
                </span>
              </label>
            </div>
            <div className="monitoring-target">
              <span>Success signal</span>
              <strong>
                Complaint share ≤ {formatPercent((data.baselineShare ?? 0) * 1.2)} after 48 hours
              </strong>
            </div>

            {created ? (
              <div className="action-success" role="status">
                <CheckCircle size={21} weight="fill" aria-hidden="true" />
                <span>
                  <strong>Action created</strong>
                  Dashboard and active actions are now updated.
                </span>
              </div>
            ) : (
              <button className="primary-button" type="button" onClick={createAction}>
                Create action <ArrowRight size={17} weight="bold" />
              </button>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}
