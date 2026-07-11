import { CaretDown, Check, MagnifyingGlass, Package, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DashboardProduct } from "../api/types";

interface ProductFilterProps {
  products: DashboardProduct[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

function productName(product: DashboardProduct): string {
  return product.shortName ?? product.name ?? `Unidentified product · ${product.id}`;
}

export function ProductFilter({ products, selectedIds, onChange }: ProductFilterProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const visibleProducts = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return products;
    return products.filter((product) =>
      [product.name, product.shortName, product.sku, product.category, product.id]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized),
    );
  }, [products, query]);

  const selected = products.filter((product) => selectedIds.includes(product.id));
  const allSelected = products.length > 0 && selected.length === products.length;
  const feedback = selected.reduce((sum, product) => sum + product.totalFeedback, 0);
  const label = allSelected
    ? "All product groups"
    : selected.length === 0
      ? "No products selected"
      : selected.length === 1
        ? productName(selected[0]!)
        : `${selected.length} products`;

  const toggleProduct = (id: string) => {
    onChange(selectedIds.includes(id)
      ? selectedIds.filter((item) => item !== id)
      : [...selectedIds, id]);
  };

  return (
    <div className="product-filter" ref={rootRef}>
      <button
        className="product-filter__trigger"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Change product scope. ${label}.`}
      >
        <span className="product-filter__trigger-icon"><Package size={21} aria-hidden="true" /></span>
        <span className="product-filter__trigger-copy">
          <span>Viewing server-grouped feedback</span>
          <strong>{label}</strong>
          <small>{selected.length} products · {feedback.toLocaleString()} feedback items</small>
        </span>
        <span className="product-filter__trigger-action">Change scope</span>
        <CaretDown size={16} weight="bold" aria-hidden="true" />
      </button>

      {open && (
        <div className="product-filter__menu" role="dialog" aria-label="Filter by products">
          <div className="product-filter__menu-head">
            <div><span className="eyebrow">Product filter</span><h3>Select products</h3></div>
            <button className="icon-button" type="button" onClick={() => setOpen(false)} aria-label="Close product filter">
              <X size={17} />
            </button>
          </div>
          <label className="product-filter__search">
            <MagnifyingGlass size={16} aria-hidden="true" />
            <input
              autoFocus
              aria-label="Search products"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search name, SKU, category or ID"
            />
          </label>
          <button
            type="button"
            className={`product-filter__all ${allSelected ? "is-selected" : ""}`}
            onClick={() => onChange(products.map((product) => product.id))}
          >
            <span className="product-filter__check">{allSelected && <Check size={13} weight="bold" />}</span>
            <span>
              <strong>All product groups</strong>
              <small>{products.length} groups from the current API response, including any unattributed bucket</small>
            </span>
          </button>
          <div className="product-filter__list">
            {visibleProducts.map((product) => {
              const isSelected = selectedIds.includes(product.id);
              return (
                <label key={product.id} className={`product-option ${isSelected ? "is-selected" : ""}`}>
                  <input type="checkbox" checked={isSelected} onChange={() => toggleProduct(product.id)} />
                  <span className="product-filter__check">{isSelected && <Check size={13} weight="bold" />}</span>
                  <span className="product-option__copy">
                    <strong>{productName(product)}</strong>
                    <small>
                      {[product.sku, product.category, product.pack].filter(Boolean).join(" · ") || `Catalog details unavailable · ${product.id}`}
                    </small>
                  </span>
                  <span className="product-option__count">
                    <strong>{product.current.feedback.toLocaleString()}</strong>
                    <small>in current window</small>
                  </span>
                </label>
              );
            })}
            {visibleProducts.length === 0 && <p className="product-filter__no-results">No matching API products.</p>}
          </div>
          <div className="product-filter__footer">
            <button className="text-button" type="button" onClick={() => onChange([])}>Clear selection</button>
            <span>{selected.length} selected</span>
          </div>
        </div>
      )}
    </div>
  );
}
