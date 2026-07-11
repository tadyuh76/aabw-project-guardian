import { useEffect, useMemo, useRef, useState } from "react";
import { CaretDown, Check, MagnifyingGlass, Package, X } from "@phosphor-icons/react";
import { PRODUCTS, type ProductId } from "../data/dashboard";

type ProductFilterProps = {
  selectedIds: ProductId[];
  onChange: (ids: ProductId[]) => void;
};

export function ProductFilter({ selectedIds, onChange }: ProductFilterProps) {
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
    const normalized = query.trim().toLowerCase();
    if (!normalized) return PRODUCTS;
    return PRODUCTS.filter((product) =>
      `${product.name} ${product.sku} ${product.category}`.toLowerCase().includes(normalized),
    );
  }, [query]);

  const isAll = selectedIds.length === PRODUCTS.length;
  const selectedProducts = PRODUCTS.filter((product) => selectedIds.includes(product.id));
  const reviewCount = selectedProducts.reduce((total, product) => total + product.ratingCount, 0);
  const averageRating = reviewCount
    ? selectedProducts.reduce((total, product) => total + product.rating * product.ratingCount, 0) / reviewCount
    : 0;
  const label = isAll
    ? "All Guardian products"
    : selectedIds.length === 0
      ? "No products selected"
      : selectedIds.length === 1
        ? PRODUCTS.find((product) => product.id === selectedIds[0])?.shortName
        : `${selectedIds.length} products`;

  const toggleProduct = (id: ProductId) => {
    const exists = selectedIds.includes(id);
    onChange(exists ? selectedIds.filter((item) => item !== id) : [...selectedIds, id]);
  };

  return (
    <div className="product-filter" ref={rootRef}>
      <button
        className="product-filter__trigger"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Change product scope. ${label}. ${selectedProducts.length} products, ${new Intl.NumberFormat("en-US").format(reviewCount)} reviews`}
      >
        <span className="product-filter__trigger-icon"><Package size={21} weight="regular" aria-hidden="true" /></span>
        <span className="product-filter__trigger-copy">
          <span>Viewing product portfolio</span>
          <strong>{label}</strong>
          <small>
            {selectedProducts.length} products · {new Intl.NumberFormat("en-US").format(reviewCount)} reviews
            {selectedProducts.length > 0 ? ` · ${averageRating.toFixed(1)} avg rating` : ""}
          </small>
        </span>
        <span className="product-filter__trigger-action">Change scope</span>
        <CaretDown size={16} weight="bold" aria-hidden="true" />
      </button>

      {open && (
        <div className="product-filter__menu" role="dialog" aria-label="Filter by products">
          <div className="product-filter__menu-head">
            <div>
              <span className="eyebrow">Product filter</span>
              <h3>Select products</h3>
            </div>
            <button className="icon-button" type="button" onClick={() => setOpen(false)}>
              <X size={17} aria-label="Close product filter" />
            </button>
          </div>

          <label className="product-filter__search">
            <MagnifyingGlass size={16} aria-hidden="true" />
            <input
              autoFocus
              aria-label="Search products"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search name, SKU or category"
            />
          </label>

          <button
            type="button"
            className={`product-filter__all ${isAll ? "is-selected" : ""}`}
            onClick={() => onChange(PRODUCTS.map((product) => product.id))}
          >
            <span className="product-filter__check">{isAll && <Check size={13} weight="bold" />}</span>
            <span>
              <strong>All Guardian products</strong>
              <small>{PRODUCTS.length} products · {new Intl.NumberFormat("en-US").format(PRODUCTS.reduce((total, product) => total + product.ratingCount, 0))} reviews</small>
            </span>
          </button>

          <div className="product-filter__list">
            {visibleProducts.map((product) => {
              const selected = selectedIds.includes(product.id);
              return (
                <label key={product.id} className={`product-option ${selected ? "is-selected" : ""}`}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleProduct(product.id)}
                  />
                  <span className="product-filter__check">
                    {selected && <Check size={13} weight="bold" />}
                  </span>
                  <span className="product-option__copy">
                    <strong>{product.name}</strong>
                    <small>{product.sku} · {product.category} · {product.pack}</small>
                  </span>
                  <span className="product-option__count">
                    <strong>{product.rating.toFixed(1)} ★</strong>
                    <small>{new Intl.NumberFormat("en-US", { notation: "compact" }).format(product.ratingCount)} reviews</small>
                  </span>
                </label>
              );
            })}
            {visibleProducts.length === 0 && (
              <p className="product-filter__no-results">No matching products.</p>
            )}
          </div>

          <div className="product-filter__footer">
            <button className="text-button" type="button" onClick={() => onChange([])}>
              Clear selection
            </button>
            <span>{selectedIds.length} selected</span>
          </div>
        </div>
      )}
    </div>
  );
}
