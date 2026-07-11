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

    expect(screen.getByRole("heading", { name: "Leakage is today's priority" })).toBeInTheDocument();
    expect(screen.getAllByText("All Guardian products").length).toBeGreaterThan(0);
    expect(screen.getByText("Complaint share")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /12 products, 68,420 reviews/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Signals" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export report" })).toBeEnabled();
  });

  it("opens the all-product dashboard from the top bar", () => {
    window.history.replaceState(null, "", "/?products=P-UV01");
    render(<App />);

    expect(screen.getByRole("button", { name: "← Back to portfolio overview" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Command Center" }));

    expect(window.location.search).toBe("?products=all");
    expect(screen.getByRole("heading", { name: "Leakage is today's priority" })).toBeInTheDocument();
  });

  it("opens the dedicated competitive benchmark from the top navigation", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Competitive Benchmark" }));

    expect(window.location.pathname).toBe("/benchmark");
    expect(screen.getByRole("heading", { name: "Competitive Benchmark" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Comparable with standardization" })).toBeInTheDocument();
    expect(screen.getByText("Standardized to Guardian product mix")).toBeInTheDocument();
    expect(screen.getByText("Reference n")).toBeInTheDocument();
    expect(screen.getByText("same comparison basis for every brand")).toBeInTheDocument();
    expect(screen.getByText("Comment drill-downs show Guardian evidence behind the comparison. Peer row-level comments are not connected in this demo.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Guardian is losing on packaging reliability." })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Complaint rate comparison between Guardian, Hasaki and Watsons" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Eight day complaint-rate trend for Guardian, Hasaki and Watsons" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Complaint topic rates for Guardian, Hasaki and Watsons" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Indexed experience profile for Guardian, Hasaki and Watsons" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "View comments related to Leaking" })[0]);
    expect(screen.getByRole("dialog", { name: "Leaking" })).toBeInTheDocument();
    expect(screen.getByText("Source pages and review records contributing to this problem.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /All pages/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close problem investigation" }));
    expect(screen.queryByRole("dialog", { name: "Leaking" })).not.toBeInTheDocument();
  });

  it("loads the benchmark route directly and returns to a focused investigation", () => {
    window.history.replaceState(null, "", "/benchmark?products=all");
    render(<App />);

    expect(screen.getByRole("button", { name: "Competitive Benchmark" })).toHaveClass("is-active");
    fireEvent.click(screen.getByRole("button", { name: /Investigate SunShield SPF 50/i }));

    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("?products=P-UV01");
    expect(screen.getByRole("button", { name: "← Back to portfolio overview" })).toBeInTheDocument();
  });

  it("leads with the all-product dashboard without the legacy incident shortcuts", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Leakage is today's priority" })).toBeInTheDocument();
    expect(screen.getByText("Viewing · All 12 products")).toBeInTheDocument();
    expect(screen.getByText("New signals today")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Estimated sentiment by product/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top issue themes" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Complaint rate by product" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Current vs 28-day baseline" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Experience signal benchmark" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Experience sentiment benchmark for Guardian, Watsons and Hasaki" })).toBeInTheDocument();
    expect(screen.getByText("Directional signal")).toBeInTheDocument();
    expect(screen.getByText("Delivery experience")).toBeInTheDocument();
    expect(screen.getAllByText("Synthetic demo data").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("row")).toHaveLength(17);
    expect(screen.queryByRole("button", { name: "Investigate incident" })).not.toBeInTheDocument();
    expect(screen.queryByText("Detailed evidence and activity")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Investigate SunShield SPF 50: Leaking" }));
    expect(window.location.search).toBe("?products=P-UV01");
    expect(screen.getByRole("button", { name: "← Back to portfolio overview" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Packaging complaint signal" })).not.toBeInTheDocument();
  });

  it("shows a real empty state and can restore the full cohort", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /change product scope/i }));
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));

    expect(
      screen.getByText("Select products to build a comparable customer-feedback cohort."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /show all products/i }));
    expect(screen.getByRole("heading", { name: "Leakage is today's priority" })).toBeInTheDocument();
  });

  it("shows each product's top problem and investigates it directly", () => {
    render(<App />);

    expect(screen.getByText("Top problem")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Investigate SunShield SPF 50: Leaking" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Investigate SunShield SPF 50: Leaking" }));
    expect(window.location.search).toBe("?products=P-UV01");
    expect(screen.queryByRole("dialog", { name: "Packaging complaint signal" })).not.toBeInTheDocument();
  });

  it("filters the product review table by platform", () => {
    render(<App />);

    expect(screen.getByLabelText("Filter reviews by platform")).toHaveValue("all");
    expect(screen.getByRole("table", { name: "Estimated sentiment by product on All platforms" })).toBeInTheDocument();
    expect(screen.getByText("Sunscreen · 480 reviews")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter reviews by platform"), { target: { value: "tiktok" } });

    expect(screen.getByRole("table", { name: "Estimated sentiment by product on TikTok" })).toBeInTheDocument();
    expect(screen.getByText("Sunscreen · 130 reviews")).toBeInTheDocument();
    expect(screen.getByText("1,556 reviews")).toBeInTheDocument();
  });

  it("updates the dashboard to a single selected product", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /change product scope/i }));
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    fireEvent.click(screen.getByText("SunShield Daily SPF 50"));
    fireEvent.click(screen.getByLabelText("Close product filter"));

    expect(screen.getByRole("heading", { name: "Users are complaining about leakage, broken caps, and poor packaging." })).toBeInTheDocument();
    expect(screen.getByText("126/480")).toBeInTheDocument();
    expect(screen.queryByText("UV Defense SPF 50+")).not.toBeInTheDocument();
  });

  it("shows the AI core insight and corrective action without opening a sidebar", () => {
    window.history.replaceState(null, "", "/?products=P-UV01");
    render(<App />);

    expect(screen.getByText("AI-generated core insight")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "Users are complaining about leakage, broken caps, and poor packaging." }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Critical").length).toBeGreaterThan(0);
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Moderate")).toBeInTheDocument();
    expect(screen.getByText("Recommended corrective action")).toBeInTheDocument();
    expect(screen.getByText("Inspect the affected packaging batch and isolate suspect units.")).toBeInTheDocument();
    expect(screen.getByText("Confirm pump-neck seal and cap-fit tolerances with Quality Assurance.")).toBeInTheDocument();
    expect(screen.getByText("Verify the e-commerce protective-wrap checkpoint before fulfilment.")).toBeInTheDocument();

    expect(screen.queryByText("Owner")).not.toBeInTheDocument();
    expect(screen.queryByText("Success signal")).not.toBeInTheDocument();

    expect(screen.queryByRole("dialog", { name: "Packaging complaint signal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Investigate this incident" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Products driving the issue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Channels confirming the issue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What customers actually reported" })).not.toBeInTheDocument();
    expect(screen.queryByText("Supporting analysis")).not.toBeInTheDocument();
  });

  it("shows top 10 product problems and navigates source review pages", () => {
    window.history.replaceState(null, "", "/?products=P-UV01");
    render(<App />);

    expect(screen.getByRole("heading", { name: "Monthly sentiment trend" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Line chart of monthly sentiment for SunShield SPF 50/i })).toBeInTheDocument();
    expect(screen.getByText(/classified reviews in Jul · Synthetic demo/)).toBeInTheDocument();

    const problemsSection = screen.getByRole("heading", { name: "Top 10 problems" }).closest("section");
    expect(problemsSection).toBeInTheDocument();
    expect(problemsSection?.querySelectorAll(".product-problem-legend button")).toHaveLength(10);
    const problemChart = screen.getByRole("img", { name: "Top 10 problems measured in customer mentions for last 72 hours shown as a horizontal bar chart" });
    expect(problemChart).toBeInTheDocument();
    expect(screen.getByText("Number of customer feedback mentions classified into each problem.")).toBeInTheDocument();
    expect(problemChart).toHaveAccessibleName(/measured in customer mentions/i);

    const problemLegend = problemsSection?.querySelector(".product-problem-legend");
    expect(problemLegend).toBeInTheDocument();
    const leakingProblem = within(problemLegend as HTMLElement).getByRole("button", { name: "Investigate Leaking" });
    /* Legacy pie hover assertions remain intentionally retired while the time-comparable bar chart is active. */

    fireEvent.click(leakingProblem);
    expect(screen.getByRole("dialog", { name: "Leaking" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /All pages/ })).toBeInTheDocument();

    const sourcePageButtons = screen.getAllByRole("button", { name: "Open source page" });
    expect(sourcePageButtons.length).toBeGreaterThan(0);
    fireEvent.click(sourcePageButtons[0]);
    expect(screen.getByRole("button", { name: "Back to all source pages" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic provenance page. A production record should expose the retained external `sourceUrl` here.")).toBeInTheDocument();
  });

  it("filters the incident, top problems and sentiment trend by time", () => {
    window.history.replaceState(null, "", "/?products=P-UV01");
    render(<App />);

    const incidentFilter = screen.getByLabelText("Filter incident by time");
    expect(incidentFilter).toHaveValue("72h");
    fireEvent.change(incidentFilter, { target: { value: "30d" } });
    expect(incidentFilter).toHaveValue("30d");
    expect(screen.getByText("743/16680")).toBeInTheDocument();
    expect(screen.getByText("last 30 days")).toBeInTheDocument();

    const problemsFilter = screen.getByLabelText("Filter top problems by time");
    expect(problemsFilter).toHaveValue("72h");
    fireEvent.change(problemsFilter, { target: { value: "24h" } });
    expect(problemsFilter).toHaveValue("24h");
    const problemsSection = screen.getByRole("heading", { name: "Top 10 problems" }).closest("section");
    expect(within(problemsSection as HTMLElement).getByText("29 mentions")).toBeInTheDocument();

    const sentimentFilter = screen.getByLabelText("Filter sentiment trend by time");
    expect(sentimentFilter).toHaveValue("6m");
    fireEvent.change(sentimentFilter, { target: { value: "3m" } });
    expect(sentimentFilter).toHaveValue("3m");
    expect(screen.getByRole("img", { name: /monthly sentiment for SunShield SPF 50 over last 3 months/i })).toBeInTheDocument();
  });

  it("compares all three time-based sections with one shared toggle", () => {
    window.history.replaceState(null, "", "/?products=P-UV01");
    render(<App />);

    const compareToggle = screen.getByRole("switch", { name: "Compare periods" });
    expect(compareToggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(compareToggle);

    expect(compareToggle).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("img", { name: "Last 72 hours compared with the previous matching period" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Top 10 problems measured in customer mentions for last 72 hours compared with the previous matching period/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /monthly sentiment for SunShield SPF 50 over last 6 months compared with the previous 6 months/i })).toBeInTheDocument();
    expect(screen.getAllByText("Current vs previous period").length).toBeGreaterThan(0);
  });

  it("keeps improving cohorts out of the legacy alert and action UI", () => {
    window.history.replaceState(null, "", "/?products=P-SE01");
    render(<App />);

    expect(screen.getByRole("heading", { name: "Users are complaining about loose dropper." })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Not enough evidence" })).not.toBeInTheDocument();
    expect(screen.queryByText("Alert: packaging complaints spike")).not.toBeInTheDocument();
    expect(screen.getByText("6/430")).toBeInTheDocument();
  });

  it("falls back safely when persisted action storage has the wrong shape", () => {
    localStorage.setItem("guardian-demo-actions", JSON.stringify({ invalid: true }));
    expect(() => render(<App />)).not.toThrow();
    expect(screen.getByRole("heading", { name: "Leakage is today's priority" })).toBeInTheDocument();
  });
});
