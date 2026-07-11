import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";

describe("product filter critical path", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/?products=all");
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("uses light mode by default and lets the user switch themes", () => {
    render(<App />);

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    const toggle = screen.getByRole("button", { name: "Switch to dark mode" });
    fireEvent.click(toggle);

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("guardian-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light mode" })).toBeInTheDocument();
  });

  it("restores a previously selected dark theme", () => {
    localStorage.setItem("guardian-theme", "dark");
    render(<App />);

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });

  it("uses all products by default", () => {
    render(<App />);

    expect(screen.getByText("Packaging complaints increased 2.3× in 72 hours")).toBeInTheDocument();
    expect(screen.getAllByText("All Guardian products").length).toBeGreaterThan(0);
    expect(screen.getAllByText("337").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /12 products, 68,420 reviews/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Signals" })).not.toBeInTheDocument();
  });

  it("leads with comprehensive portfolio sentiment and opens the focused incident", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "How customers feel across all products" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Estimated sentiment by product" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top negative themes" })).toBeInTheDocument();
    expect(screen.getByText("Demo-derived sentiment")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(13);

    fireEvent.click(screen.getByRole("button", { name: "Investigate incident" }));
    expect(window.location.search).toBe("?products=P-UV01%2CP-UV02");
    expect(screen.getByRole("heading", { name: "Leaking complaints spiked across 2 sunscreen products" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "← Back to portfolio overview" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Investigate this incident" }));
    expect(screen.getByRole("dialog", { name: "Packaging complaint signal" })).toBeInTheDocument();
  });

  it("shows a real empty state and can restore the full cohort", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /change product scope/i }));
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));

    expect(
      screen.getByText("Select products to build a comparable customer-feedback cohort."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /show all products/i }));
    expect(screen.getByText("Packaging complaints increased 2.3× in 72 hours")).toBeInTheDocument();
  });

  it("shows each product's top problem and investigates it directly", () => {
    render(<App />);

    expect(screen.getByText("Top problem")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Investigate SunShield SPF 50: Leaking" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Investigate SunShield SPF 50: Leaking" }));
    expect(window.location.search).toBe("?products=P-UV01");
    expect(screen.getByRole("dialog", { name: "Packaging complaint signal" })).toBeInTheDocument();
  });

  it("updates the dashboard to a single selected product", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /change product scope/i }));
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    fireEvent.click(screen.getByText("SunShield Daily SPF 50"));
    fireEvent.click(screen.getByLabelText("Close product filter"));

    expect(screen.getByText(/SunShield SPF 50 complaints increased 6.9×/)).toBeInTheDocument();
    expect(screen.getAllByText("126").length).toBeGreaterThan(0);
    expect(screen.queryByText("UV Defense SPF 50+")).not.toBeInTheDocument();
  });

  it("shows top 10 product problems and navigates source review pages", () => {
    window.history.replaceState(null, "", "/?products=P-UV01");
    render(<App />);

    const problemsSection = screen.getByRole("heading", { name: "Top 10 problems" }).closest("section");
    expect(problemsSection).toBeInTheDocument();
    expect(problemsSection?.querySelectorAll(".product-problem-legend button")).toHaveLength(10);
    expect(screen.getByRole("img", { name: "Top 10 problems by share of problem mentions. Select a slice to investigate." })).toBeInTheDocument();

    const problemLegend = problemsSection?.querySelector(".product-problem-legend");
    expect(problemLegend).toBeInTheDocument();
    fireEvent.click(within(problemLegend as HTMLElement).getByRole("button", { name: "Investigate Leaking" }));
    expect(screen.getByRole("dialog", { name: "Leaking" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /All pages/ })).toBeInTheDocument();

    const sourcePageButtons = screen.getAllByRole("button", { name: "Open source page" });
    expect(sourcePageButtons.length).toBeGreaterThan(0);
    fireEvent.click(sourcePageButtons[0]);
    expect(screen.getByRole("button", { name: "Back to all source pages" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic provenance page. A production record should expose the retained external `sourceUrl` here.")).toBeInTheDocument();
  });

  it("keeps improving cohorts out of the alert and action path", () => {
    window.history.replaceState(null, "", "/?products=P-SE01");
    render(<App />);

    expect(screen.getByText("Radiance C15 Serum complaints improved below baseline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not enough evidence" })).toBeDisabled();
    expect(screen.queryByText("Alert: packaging complaints spike")).not.toBeInTheDocument();
    expect(screen.getByText("-0.5pp")).toBeInTheDocument();
    expect(screen.getByText("-0.4pp")).toBeInTheDocument();
  });

  it("falls back safely when persisted action storage has the wrong shape", () => {
    localStorage.setItem("guardian-demo-actions", JSON.stringify({ invalid: true }));
    expect(() => render(<App />)).not.toThrow();
    expect(screen.getByText("Alert: packaging complaints spike")).toBeInTheDocument();
  });
});
